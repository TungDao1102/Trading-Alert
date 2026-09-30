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

All commands run from the repo root as `.venv/Scripts/python -m pytest <files> -q -p no:cacheprovider` (shortened to `pytest <files>` below).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-T1 | 13-01 | 1 | DATA-02 (D-01/D-02/D-03) | T-13-01, T-13-02 | collect list validated, empty rejected, no LIVE_5 fallback | unit | `pytest tests/test_collect_list.py tests/test_collector.py` | W0 created in task (RED) | ⬜ pending |
| 13-01-T2 | 13-01 | 1 | DATA-02 (D-01/D-02/D-24) | T-13-01, T-13-03, T-13-04 | proposer keeps only TRADING PERPETUAL USDT; committed list loads; Dockerfile copies it | unit + human-check | `pytest tests/test_collect_list.py` | extend | ⬜ pending |
| 13-01-T3 | 13-01 | 1 | DATA-02 (Pitfall 5) | — | loop sleeps to the next cadence boundary | unit | `pytest tests/test_collector.py` | extend | ⬜ pending |
| 13-02-T1 | 13-02 | 1 | DATA-01 (D-13, D-29) | T-13-05 | current UTC day never published; partial past day held back | unit | `pytest tests/test_backfill_closed_day.py tests/test_backfill.py tests/test_tracer_slice.py` | W0 created in task + rewrite 7 tests | ⬜ pending |
| 13-02-T2 | 13-02 | 1 | DATA-01 (D-14) | T-13-06, T-13-07, T-13-09 | interrupted write leaves no partial file | unit | `pytest tests/test_store_atomic.py` | W0 created in task | ⬜ pending |
| 13-02-T3 | 13-02 | 1 | DATA-01 (D-15) | T-13-08 | zero-trade accepted; gaps stay gaps; more than 8 decimals rejected | unit | `pytest tests/test_quality_gates.py tests/test_backfill_closed_day.py` | extend | ⬜ pending |
| 13-03-T1 | 13-03 | 1 | DATA-01 (D-16) | T-13-11, T-13-12 | backfill before resubscribe (shared call log) | unit | `pytest tests/test_paper_supervisor_backfill.py tests/test_paper_resync.py` | extend | ⬜ pending |
| 13-03-T2 | 13-03 | 1 | DATA-01 (D-28) | T-13-10, T-13-11 | no duplicate or skipped bar across the seam | unit | `pytest tests/test_paper_supervisor_backfill.py` | extend | ⬜ pending |
| 13-04-T1 | 13-04 | 2 | DATA-01 (D-11, D-12, D-29) | T-13-13, T-13-14 | mark klines in their own root, no volume/trade_count | unit | `pytest tests/test_mark_klines.py` | W0 created in task | ⬜ pending |
| 13-04-T2 | 13-04 | 2 | DATA-03 (D-26), DATA-02 (Pitfall 9) | T-13-16 | deliveryDate, empty markPrice -> None, server time, -1121 predicate | unit | `pytest tests/test_adapter_strictness.py` | extend | ⬜ pending |
| 13-04-T3 | 13-04 | 2 | DATA-04 (D-27) | T-13-15, T-13-17 | per-dataset cursors, trade view disjoint, backup covers mark subtree | unit | `pytest tests/test_mark_klines.py tests/test_backup.py tests/test_coverage.py` | extend | ⬜ pending |
| 13-05-T1 | 13-05 | 2 | DATA-01 (D-08) | T-13-18 | archive month publishes the same frames as REST | unit (respx) | `pytest tests/test_archive_ingest.py` | W0 created in task | ⬜ pending |
| 13-05-T2 | 13-05 | 2 | DATA-01 (D-08, D-26) | T-13-18, T-13-19, T-13-20, T-13-21 | checksum mismatch fails closed, size caps, no disk extraction, traversal rejected | unit (respx) | `pytest tests/test_archive_ingest.py` | extend | ⬜ pending |
| 13-05-T3 | 13-05 | 2 | DATA-01 (D-08) | T-13-20, T-13-22 | bucket listing validated and bounded; last archive day | unit (respx) | `pytest tests/test_archive_ingest.py` | extend | ⬜ pending |
| 13-06-T1 | 13-06 | 3 | DATA-02 (D-23) | T-13-24, T-13-26 | paginated funding history, no duplicate ticks | unit | `pytest tests/test_collector.py` | extend | ⬜ pending |
| 13-06-T2 | 13-06 | 3 | DATA-02 (F-408) | T-13-25 | atomic OI/funding tick writes | unit | `pytest tests/test_collector.py` | extend | ⬜ pending |
| 13-06-T3 | 13-06 | 3 | DATA-02 (D-25, F-706) | T-13-27 | warn-only server-time probe never blocks start | unit | `pytest tests/test_collector.py` | extend | ⬜ pending |
| 13-07-T1 | 13-07 | 3 | DATA-01, DATA-03 (D-04, F-122) | T-13-31, T-13-32 | metadata first; depth printed | unit | `pytest tests/test_backfill_cli.py` | W0 created in task | ⬜ pending |
| 13-07-T2 | 13-07 | 3 | DATA-01 (D-04, D-07, D-26) | T-13-29, T-13-33 | delivery cap, onboard floor, frozen htf start, resume | unit | `pytest tests/test_backfill_cli.py` | extend | ⬜ pending |
| 13-07-T3 | 13-07 | 3 | DATA-03 (D-10, D-29) | T-13-30 | versioned insert for SETTLING/PENDING symbols, universe filter, width guard | unit (SQLite) | `pytest tests/test_metadata.py tests/test_backfill_cli.py` | extend | ⬜ pending |
| 13-08-T1 | 13-08 | 4 | DATA-01 (D-05) | T-13-44, T-13-46 | exit 3 only for missing data; floor stated unmeasurable | unit | `pytest tests/test_sufficiency.py tests/test_backfill_cli.py` | W0 created in task | ⬜ pending |
| 13-08-T2 | 13-08 | 4 | DATA-01 (D-21) | T-13-46 | per-split 1m coverage on the 40/40/20 timeline | unit | `pytest tests/test_sufficiency.py` | extend | ⬜ pending |
| 13-08-T3 | 13-08 | 4 | DATA-01, DATA-02 (D-08, D-23) | T-13-45, T-13-47 | archive fallback recorded per symbol; funding step | unit | `pytest tests/test_backfill_cli.py tests/test_sufficiency.py tests/test_archive_ingest.py tests/test_collector.py` | extend | ⬜ pending |
| 13-09-T1 | 13-09 | 3 | BKTS-02 (D-17, D-18, D-22) | T-13-34 | store -> case input -> simulator -> assemble(data_snapshot_id) | unit | `pytest tests/test_case_input_builder.py tests/test_backtest_experiment.py` | W0 created in task | ⬜ pending |
| 13-09-T2 | 13-09 | 3 | BKTS-02 (D-19) | T-13-35, T-13-36 | gap refusal, allow list recorded, current day refused | unit | `pytest tests/test_coverage.py tests/test_case_input_builder.py` | extend | ⬜ pending |
| 13-09-T3 | 13-09 | 3 | BKTS-02 (D-18) | T-13-34, T-13-37, T-13-38 | deterministic dataset hash, change-sensitive, no clock/float | unit | `pytest tests/test_case_input_builder.py tests/test_coverage.py tests/test_domain_no_float.py` | extend | ⬜ pending |
| 13-10-T1 | 13-10 | 3 | DATA-01, BKTS-02 (D-09) | T-13-39 | freeze writes matching witnesses (tmp copies) | unit | `pytest tests/test_universe_freeze.py tests/test_decision_alignment_universe.py` | W0 created in task | ⬜ pending |
| 13-10-T2 | 13-10 | 3 | DATA-01 (D-06, D-07, D-08) | T-13-41, T-13-42 | ranking rules; unavailable listed, never dropped | unit | `pytest tests/test_universe_freeze.py` | extend | ⬜ pending |
| 13-10-T3 | 13-10 | 3 | DATA-01 (D-09) | T-13-39, T-13-40 | explicit --freeze, approval hash, no re-freeze | unit + gate | `pytest tests/test_universe_freeze.py tests/test_decision_alignment_universe.py`; `python scripts/verify_decision_alignment.py universe` | extend | ⬜ pending |
| 13-11-T1 | 13-11 | 5 | DATA-01..04, BKTS-02 | T-13-48 | exchange facts recorded with source and date | gate | `python scripts/verify_decision_alignment.py docs` | n/a (docs) | ⬜ pending |
| 13-11-T2 | 13-11 | 5 | DATA-01..04 (D-27) | T-13-48 | datasets, rules and settings documented | gate | `python scripts/verify_decision_alignment.py docs` and `decisions` | n/a (docs) | ⬜ pending |
| 13-11-T3 | 13-11 | 5 | BKTS-02 | T-13-49 | D049 recorded; requirements gate maps OPS-06 to 13.1 | gate + unit | `pytest tests/test_decision_alignment_bookkeeping.py`; `python scripts/verify_decision_alignment.py all` | extend | ⬜ pending |
| 13-12-T1 | 13-12 | 4 | DATA-01 (D-06..D-08) | T-13-52 | live proposal report written and hash-verified | CLI (precondition: Python TLS to Binance) | `python -c "... load_report(DEFAULT_REPORT_PATH) ..."` | n/a | ⬜ pending |
| 13-12-T2 | 13-12 | 4 | D-09 | T-13-51 | human decides the one-way freeze | checkpoint:decision (blocking-human) | manual | n/a | ⬜ pending |
| 13-12-T3 | 13-12 | 4 | DATA-01, BKTS-02 (D-09) | T-13-50, T-13-51 | FROZEN manifest and witness equal, one commit | gate + unit | `python scripts/verify_decision_alignment.py universe`; `pytest tests/test_decision_alignment_universe.py tests/test_universe_freeze.py` | extend | ⬜ pending |
| 13-13-T1 | 13-13 | 5 | DATA-02 (D-24) | T-13-53 | re-issued list adds only TRADING frozen symbols | unit | `pytest tests/test_collect_list.py tests/test_collector.py` | extend | ⬜ pending |
| 13-13-T2 | 13-13 | 5 | DATA-01, DATA-02 (D-04) | T-13-55 | real backfill run and collector restart | checkpoint:human-action | manual | n/a | ⬜ pending |
| 13-13-T3 | 13-13 | 5 | DATA-01 (D-05, D-21) | T-13-54 | sufficiency report validated and committed unchanged | CLI | `python -m src.data.sufficiency validate docs/research/universe/research-universe-v1.sufficiency-report.json` | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky.*

---

## Wave 0 Requirements

- [ ] `tests/test_collect_list.py` (13-01-T1), `tests/test_store_atomic.py` (13-02-T2), `tests/test_backfill_closed_day.py` (13-02-T1), `tests/test_mark_klines.py` (13-04-T1), `tests/test_backfill_cli.py` (13-07-T1), `tests/test_archive_ingest.py` (13-05-T1), `tests/test_universe_freeze.py` (13-10-T1), `tests/test_case_input_builder.py` (13-09-T1), `tests/test_sufficiency.py` (13-08-T1); each is created in the RED step of the named task
- [ ] `tests/fixtures/phase13/freeze/research-universe-v1.draft.toml` (13-10-T1) so freeze and DRAFT-rejection tests never depend on the real manifest's state
- [ ] Fixtures: trimmed exchangeInfo (~6 symbols incl. SETTLING with `deliveryDate`, PENDING_TRADING, TRADIFI_PERPETUAL, quarterly, USDC), recorded markPriceKlines sample, funding sample with `"markPrice":""`, in-test zip + `.CHECKSUM`
- [ ] Shared fake adapter supporting `klines`, `mark_klines`, `exchange_info`, `funding_rate`
- [ ] Rewrite `test_forming_candle_at_frozen_now_is_excluded` and `test_paginator_drops_forming_candle_at_frozen_clock`; update `test_real_manifest_is_draft_with_empty_freeze_fields` in the freeze commit

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Run the widened collector for a day on a real host | DATA-02 | Needs a live Binance connection and wall-clock time | Start the collector, confirm watermarks advance for every collect-list symbol |
| Freeze the research universe | D-09 | Deliberate operator action against live data (13-12-T2 checkpoint:decision) | Review the `propose` report and its proposal_sha256, choose an option, then 13-12-T3 runs `freeze --approve <sha> --freeze` and commits both witnesses in one commit |
| Real research-universe backfill | DATA-01, D-04, D-05 | Hours of wall clock, PostgreSQL and Binance TLS access (13-13-T2 checkpoint:human-action) | Run `python -m src.data.backfill_cli --report-out docs/research/universe/research-universe-v1.sufficiency-report.json`; re-run to resume; report exit code |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
