---
phase: "11"
slug: decision-alignment
status: complete
nyquist_compliant: true
wave_0_complete: true
created: "2026-09-30"
---

# Phase 11 — Validation Strategy

> Per-phase validation contract. Source: `11-RESEARCH.md` § Validation Architecture.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 (`pyproject.toml` `[tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_kill_gate_docs.py tests/test_kill_gate_clock.py tests/test_kill_gate_registration.py tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_research_gate_negative.py tests/test_decision_alignment*.py -q -p no:cacheprovider` |
| **Full suite command** | `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` |
| **Verify script** | `.venv/Scripts/python scripts/verify_decision_alignment.py all` |
| **Estimated runtime** | quick ~30 s; full a few minutes |

## Sampling Rate

- **After every task commit:** quick run command
- **After every plan wave:** full suite
- **Before `/gsd-verify-work`:** full suite green and `verify_decision_alignment.py all` prints `ALL_PASS all`

## Per-Task Verification Map

| Task | Req | Behavior | Test Type | Automated Command | File Exists |
|------|-----|----------|-----------|-------------------|-------------|
| 11-01-01 | RSCH-01 | version-bound freeze step proven by running the real workflow step against synthetic witness triplets | integration | `pytest tests/test_research_gate_negative.py tests/test_kill_gate_clock.py tests/test_kill_gate_docs.py -q -p no:cacheprovider` | exists |
| 11-01-02 | RSCH-01 | header, DECISIONS row D043, DOC_STATUS agree at v1.1.0; D029/D030/D032 unchanged | unit | `pytest tests/test_kill_gate_docs.py tests/test_kill_gate_clock.py tests/test_kill_gate_registration.py tests/test_research_gate_negative.py tests/test_analytics_files.py -q -p no:cacheprovider` | exists |
| 11-01-03 | RSCH-01 | pre-registration body, holdout marker, BACKTEST_SPEC pointers, protocol gates | script + unit | `pytest tests/test_decision_alignment_protocol.py tests/test_kill_gate_docs.py tests/test_kill_gate_clock.py tests/test_kill_gate_registration.py tests/test_research_gate_negative.py -q -p no:cacheprovider`; `verify_decision_alignment.py protocol` | exists |
| 11-02-01 | RSCH-01/RSCH-02 | working_type key loads, pins registered, family scan unaffected | unit | `pytest tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py -q -p no:cacheprovider`; `mypy src/domain/registry.py` | exists |
| 11-02-02 | RSCH-01/RSCH-02 | candidate sets for breakout-retest and range-mr, candidate-id expectations | unit | `pytest tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_backtest_binding.py tests/test_backtest_experiment.py -q -p no:cacheprovider` | exists |
| 11-02-03 | RSCH-01/RSCH-02 | baseline sets, byte lock on the ten old files, params gates | script + unit | `pytest tests/test_decision_alignment_params.py tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_paper_freeze.py tests/test_backtest_binding.py -q -p no:cacheprovider`; `verify_decision_alignment.py params` | exists |
| 11-03-01 | RSCH-01 | D039 universe manifest DRAFT, validator and gate | unit | `pytest tests/test_decision_alignment_universe.py tests/test_kill_gate_registration.py tests/test_analytics_files.py -q -p no:cacheprovider` | exists |
| 11-03-02 | RSCH-01 | freeze-path hashing, CLI, CI-safety guards | script + unit | `pytest tests/test_decision_alignment_universe.py -q -p no:cacheprovider`; `python -m scripts.decision_alignment.universe docs/research/universe/research-universe-v1.toml`; `verify_decision_alignment.py universe` | exists |
| 11-04-01 | OPS-01/EXEC-02 | SAFE_MODE entries-only ladder across SECURITY_AND_OPERATIONS and RUNBOOK | script | `pytest tests/test_decision_alignment_ops_risk.py -q -p no:cacheprovider`; `verify_decision_alignment.py docs` | exists |
| 11-04-02 | RISK-02 | daily loss, margin, costs, SL integrity, quantization-order text; no stale wording | script | `pytest tests/test_decision_alignment_ops_risk.py -q -p no:cacheprovider`; `verify_decision_alignment.py docs` | exists |
| 11-04-03 | RISK-02/OPS-01 | DATA_MODEL plan fields, CONFIGURATION keys, alert example | script | `pytest tests/test_decision_alignment_ops_risk.py -q -p no:cacheprovider`; `ruff check scripts/decision_alignment/ops_risk.py tests/test_decision_alignment_ops_risk.py` | exists |
| 11-05-01 | EXEC-02/OPS-01 | 200 account-wide conditional-order limit corrected, source registered | script | `pytest tests/test_decision_alignment_exchange.py -q -p no:cacheprovider`; `verify_decision_alignment.py docs` | exists |
| 11-05-02 | EXEC-02/OPS-01 | algo status semantics, position-mode citation, orphan/reconciler, emergency controls | script | `pytest tests/test_decision_alignment_exchange.py -q -p no:cacheprovider`; `verify_decision_alignment.py docs` | exists |
| 11-05-03 | EXEC-02/OPS-01 | BINANCE.md WebSocket split, workingType default; wrong coin-futures citations fixed | script | `pytest tests/test_decision_alignment_exchange.py tests/test_kill_gate_docs.py -q -p no:cacheprovider`; `ruff check scripts/decision_alignment/exchange.py tests/test_decision_alignment_exchange.py` | exists |
| 11-06-01 | RISK-02/EXEC-02 | TradingView authentication truth (no HMAC claim), generated AGENTS.md row | script | `pytest tests/test_decision_alignment_authority.py -q -p no:cacheprovider`; `verify_decision_alignment.py docs` | exists |
| 11-06-02 | RISK-02/EXEC-02 | canonical quantization order four-way agreement | script | `pytest tests/test_decision_alignment_authority.py -q -p no:cacheprovider`; `ruff check scripts/decision_alignment/authority.py tests/test_decision_alignment_authority.py` | exists |
| 11-07-01 | F-110 | GLOSSARY has no synonym pairs; reason codes derived from src/; ApprovalResult listed | script | `pytest tests/test_decision_alignment_bookkeeping.py tests/test_kill_gate_docs.py tests/test_domain_enums.py -q -p no:cacheprovider`; `verify_decision_alignment.py glossary` | exists |
| 11-07-02 | F-116 | new REQ-IDs in list, traceability and ROADMAP lines | script | `pytest tests/test_decision_alignment_bookkeeping.py -q -p no:cacheprovider`; `verify_decision_alignment.py reqs` | exists |
| 11-07-03 | D044/D045 | DECISIONS rows, DOC_STATUS log, DATA_MODEL exclusion notes | script | `pytest tests/test_decision_alignment_bookkeeping.py tests/test_kill_gate_docs.py tests/test_research_gate_negative.py -q -p no:cacheprovider`; `verify_decision_alignment.py decisions` | exists |
| 11-08-01 | all | dispatcher: PASS/FAIL lines, exit codes, mode routing, minimum-gate-count guard, read-only | unit + subprocess | `pytest tests/test_decision_alignment.py -q -p no:cacheprovider`; `verify_decision_alignment.py all` | exists |
| 11-08-02 | all | registry-gate CI runs the verify script and the freeze, clock, negative and alignment tests | static | `pytest tests/test_decision_alignment.py tests/test_research_gate_negative.py tests/test_kill_gate_clock.py tests/test_kill_gate_docs.py tests/test_registry.py tests/test_registry_gate.py -q -p no:cacheprovider` | exists |
| 11-08-03 | all | phase close: full suite, hygiene diffs against 679825c, lint and typing | full | `pytest tests -q -p no:cacheprovider`; `verify_decision_alignment.py all`; `ruff check` (Phase 11 files); `mypy src/domain/registry.py` | exists |

## Wave 0 Requirements

- [x] `tests/test_decision_alignment.py` and `scripts/verify_decision_alignment.py`
- [x] `tests/test_research_gate_negative.py`
- [x] loader tests for `working_type` in `tests/test_registry.py`
- [x] new pins in `tests/fixtures/phase4/parameters.json` (appended only)
- [x] `_EXPECTED_CANDIDATE_IDS` update in `tests/test_analytics_files.py`

## Manual-Only Verifications

| Behavior | Why Manual | Instructions | Status |
|----------|------------|--------------|--------|
| ALGO_UPDATE status wording | Binance docs page returns only a JS shell to WebFetch | Re-open the official page in a browser before finalizing the wording | OPEN: `docs/SOURCES.md` (plan 11-05) records the wording as taken from the SDK model plus a search summary, needing re-confirmation on the official page before Phase 18; verify markers are kept in the docs |

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity maintained
- [x] `nyquist_compliant: true` set after execution

**Approval:** approved 2026-09-30 (full suite exit 0: 1603 passed, 7 skipped; `verify_decision_alignment.py all` prints `ALL_PASS all` with 64 PASS lines; ruff and mypy clean; hygiene diffs against 679825c clean). The open manual-only ALGO_UPDATE re-confirmation is tracked for Phase 18 and does not block this phase.
