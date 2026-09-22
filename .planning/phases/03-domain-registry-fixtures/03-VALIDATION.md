---
phase: "3"
slug: "domain-registry-fixtures"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-22"
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `03-RESEARCH.md` ## Validation Architecture (Nyquist enabled, tdd_mode true).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 + pytest-asyncio (auto mode; no decorators needed) |
| **Config file** | `pyproject.toml:46-51` (`testpaths = ["tests"]`, `asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/test_domain_enums.py tests/test_registry.py -x -q` |
| **Full suite command** | `uv run pytest -q` plus `uv run python scripts/check_migration_parity.py` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick command for the touched area (`uv run pytest tests/test_<area>.py -x -q`) + `ruff check` + `mypy` on `src/` (strict)
- **After every plan wave:** Run `uv run pytest -q` + `uv run python scripts/check_migration_parity.py`
- **Before `/gsd-verify-work`:** Full suite + parity + gate workflow green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | DOMN-01 | — | 7 entities persist separately, no nullable-state inference | unit | `uv run pytest tests/test_domain_mappers.py tests/test_domain_enums.py -x -q` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | DOMN-01 | — | migration 0002 matches ORM 1:1 | static | `uv run python scripts/check_migration_parity.py` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | DOMN-02 | T-reg | registered set loads, hash stable, Decimal exact | unit | `uv run pytest tests/test_registry.py -x -q` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 1 | DOMN-02 | T-reg | unregistered/mutated sets raise; CI gate rejects | unit+CI | `uv run pytest tests/test_registry_gate.py -x -q` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | DOMN-03 | — | golden triple loads byte-exact | unit | `uv run pytest tests/test_fixture_harness.py -x -q` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 2 | DOMN-03 | — | no-lookahead / prefix-invariance / close-timing / boundary green | unit | `uv run pytest tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_domain_boundary.py -x -q` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 2 | DOMN-01 | — | no `float(` in domain/mapper/registry | static | `uv run pytest tests/test_domain_no_float.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `src/domain/` package (`enums.py`, `ids.py`, `canonical.py`, 7 entity modules, `registry.py`)
- [ ] `src/db/mappers.py` + 7 ORM tables + `0002_domain_registry.py` migration
- [ ] `params/<strategy_id>/` seed TOML(s)
- [ ] `tests/fixtures/phase3/{candles.csv,parameters.json,expected_signals.json,expected_plans.json}`
- [ ] `tests/conftest.py` extensions + `tests/test_*.py` suite files above
- [ ] CI gate extension for registry rejection (planner verifies Phase-1 gate file first)
- [ ] Framework install: none — pytest/Ruff/mypy already in `dev` extras

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live `alembic upgrade head` applies 0002 cleanly on PG17 | DOMN-01 | needs running PG17 (Compose) | Operator: boot Compose PG, run upgrade, confirm 7 tables exist |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
