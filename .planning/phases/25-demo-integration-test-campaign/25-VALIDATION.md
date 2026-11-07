---
phase: "25"
slug: "demo-integration-test-campaign"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-11-07"
---

# Phase 25 — Validation Strategy

> Seeded by plan-phase from `25-RESEARCH.md` "Validation Architecture". The planner copies task-level rows into
> the Per-Task Verification Map. Agents run only fake-exchange twins and unit tests; Demo runs are owner-only.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1, `asyncio_mode = "auto"`, pytest-xdist (dev extra; never for `demo` tests) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (the `demo` marker is added in Wave 0) |
| **Quick run command** | `uv run pytest tests/test_demo_twin_s04_sl_rejected.py -x` (one twin) |
| **Phase suite command** | `uv run pytest tests/test_demo_twin_*.py tests/test_phase25_gate.py tests/test_demo_marker_guard.py -x -q` |
| **Full suite command** | `uv run pytest -m "not docker" -n 4`; recorded gate: sequential, clean tree, `TEST_DATABASE_URL`, `TRADING_CI_STRICT=1` |
| **Owner Demo command** | `uv run pytest -m demo -p no:xdist -s` with the env guard set (owner only, never an agent) |
| **Estimated runtime** | twin under 30 s each; phase suite a few minutes; full ~10 min |

## Sampling Rate

- **After every task commit:** the single twin or unit file the task touched, plus `uv run ruff check <paths>`
- **After every plan wave:** the phase suite command
- **Before `/gsd-verify-work`:** full suite green; recorded sequential gate; `uv run mypy src`; `uv lock --check`; `uv run python scripts/verify_decision_alignment.py all`
- **Max feedback latency:** 120 s

## Per-Task Verification Map

Filled by the planner. Requirement-to-test map (from research): EXEC-01/02/03, APRV-01/02, OPS-01/02, D-03, D-08, D-11, R-24, soak evaluator, criterion-4 document gate. Status key: ⬜ pending, ✅ green, ❌ red, ⚠️ flaky.

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| (planner fills) | | | | | | | ⬜ pending |

## Wave 0 Requirements

- [ ] `pyproject.toml` marker `demo`; `tests/conftest.py` collection hook; `tests/demo/conftest.py` env guard; `tests/test_demo_marker_guard.py`
- [ ] `tests/support/fault_edge.py` with its own unit tests
- [ ] `tests/support/demo_scenarios/` skeleton, `catalog.py`, `evidence_index.py`
- [ ] Demo-side environment factory calling `build_wiring(exchange_edge=...)`
- [ ] Coverage inventory mapping S01-S20 to existing tests
- [ ] D-08 allow-list test and `tests/test_phase25_gate.py`
- [ ] Failing tests first for R-24 and R-25 (`tdd_mode` on)
- [ ] `scripts/evaluate_demo_soak.py` with fixture-journal tests

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All scenarios S01-S20 on Binance Demo with recorded order ids | EXEC-01..03, APRV-01/02, OPS-01/02 | Owner-only (AGENTS.md); agents cannot reach or may not call Demo | Owner session, `-m demo`; evidence files are the proof |
| Demo soak of at least 3 weeks | criterion 3 | Owner-started, host actions, needs owner decisions on trade generation | Pre-registered soak file; evaluator over the live journal |
| Real HTTP 418 | D-07 | Owner decided 2026-10-22 not to provoke it | Stays NOT_OBSERVED; 418/429 injected at the edge |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120 s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
