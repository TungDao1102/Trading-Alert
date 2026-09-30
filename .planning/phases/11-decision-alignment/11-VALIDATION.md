---
phase: "11"
slug: decision-alignment
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-30"
---

# Phase 11 — Validation Strategy

> Per-phase validation contract. Source: `11-RESEARCH.md` § Validation Architecture.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 (`pyproject.toml` `[tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_kill_gate_docs.py tests/test_kill_gate_clock.py tests/test_kill_gate_registration.py tests/test_registry.py tests/test_registry_gate.py tests/test_analytics_files.py tests/test_decision_alignment.py tests/test_research_gate_negative.py -q -p no:cacheprovider` |
| **Full suite command** | `.venv/Scripts/python -m pytest tests -q -p no:cacheprovider` |
| **Verify script** | `.venv/Scripts/python scripts/verify_decision_alignment.py all` |
| **Estimated runtime** | quick ~30 s; full a few minutes |

## Sampling Rate

- **After every task commit:** quick run command
- **After every plan wave:** full suite
- **Before `/gsd-verify-work`:** full suite green and `verify_decision_alignment.py all` prints `ALL_PASS all`

## Per-Task Verification Map

| Req | Behavior | Test Type | Automated Command | File Exists |
|-----|----------|-----------|-------------------|-------------|
| RSCH-01 | header, DECISIONS row, DOC_STATUS agree at v1.1.0; D030 section unchanged | unit | `pytest tests/test_kill_gate_docs.py tests/test_decision_alignment.py -q` | ❌ W0 |
| RSCH-01 | research-gate fails when any witness is missing | integration | `pytest tests/test_research_gate_negative.py -q` | ❌ W0 |
| RSCH-02 | family independence unaffected by v4 sets | unit | `pytest tests/test_analytics_files.py -q` | update ids |
| RSCH-01/DOMN-02 | v4 sets load, are pinned, old hashes unchanged | unit | `pytest tests/test_registry.py tests/test_registry_gate.py -q` | add tests |
| RISK-02 | daily loss, margin, quantization-order text; no stale wording | script | `verify_decision_alignment.py docs` | ❌ W0 |
| EXEC-02/OPS-01 | SAFE_MODE entries-only; 200 account-wide; algo semantics; WS split | script | `verify_decision_alignment.py docs` | ❌ W0 |
| F-110 | GLOSSARY has no synonym pairs; ApprovalResult listed | script | `verify_decision_alignment.py glossary` | ❌ W0 |
| F-116 | new REQ-IDs in list and traceability | script | `verify_decision_alignment.py reqs` | ❌ W0 |
| D039 | universe manifest schema and hash | script | `verify_decision_alignment.py universe` | ❌ W0 |

## Wave 0 Requirements

- [ ] `tests/test_decision_alignment.py` and `scripts/verify_decision_alignment.py`
- [ ] `tests/test_research_gate_negative.py`
- [ ] loader tests for `working_type` in `tests/test_registry.py`
- [ ] new pins in `tests/fixtures/phase4/parameters.json`
- [ ] `_EXPECTED_CANDIDATE_IDS` update in `tests/test_analytics_files.py`

## Manual-Only Verifications

| Behavior | Why Manual | Instructions |
|----------|------------|--------------|
| ALGO_UPDATE status wording | Binance docs page returns only a JS shell to WebFetch | Re-open the official page in a browser before finalizing the wording |

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity maintained
- [ ] `nyquist_compliant: true` set after execution

**Approval:** pending
