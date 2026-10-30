---
phase: "24"
slug: "live-runtime-composition-demo"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-30"
---

# Phase 24 — Validation Strategy

> Per-phase validation contract. The requirement-to-test map and Wave 0 gap list live in `24-RESEARCH.md` section "Validation Architecture"; the planner copies task-level rows here.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1, pytest-asyncio (`asyncio_mode = "auto"`), pytest-xdist (dev extra) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`, `tests/conftest.py` |
| **Quick run command** | `uv run pytest tests/test_live_*.py tests/test_phase24_gate.py -x -q` |
| **Full suite command** | `uv run pytest -m "not docker" -n 4` (orchestrator, once per phase) |
| **Estimated runtime** | quick ~60 s; full ~10 min |

## Sampling Rate

- **After every task commit:** the plan's own test files, `uv run ruff check <paths>`, `uv run mypy src/live`
- **After every plan wave:** quick command plus `tests/test_phase18_gate.py`, `tests/test_paper_shadow_isolation.py`, phase 19 to 23 gates
- **Before `/gsd-verify-work`:** full suite green; recorded sequential gate with `TEST_DATABASE_URL`
- **Max feedback latency:** 120 s

## Per-Task Verification Map

Filled by the planner per task. Requirement coverage: APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04 (see research map).

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | | | | | | ❌ W0 | ⬜ pending |

## Wave 0 Requirements

See `24-RESEARCH.md` "Wave 0 Gaps": `tests/support/live_rig.py`, fake-exchange extensions, lagging-algo-cancel fake, user-data frame injector, PTB update fake, PG restart fixtures, amended Phase 18 gate and isolation tests.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Demo end-to-end smoke with recorded order ids | EXEC-01..03 | Owner-only (AGENTS.md); machine cannot reach Binance | `scripts/demo_rehearsal.py --execute` by the owner |
| Unknown-chat / other-user tap rejected live (G2-014) | APRV-01 | Needs a second Telegram account | Owner check list |
| VPS bootstrap, IP whitelist, heartbeat firing | OPS-02, OPS-03 | Host actions | RUNBOOK sections 13 and 17 |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
