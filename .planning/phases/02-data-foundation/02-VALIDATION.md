---
phase: "2"
slug: "data-foundation"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-19"
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio (auto mode) |
| **Config file** | none — Wave 0 installs (greenfield, no pyproject.toml yet) |
| **Quick run command** | `uv run pytest -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -x -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | DATA-01 | — | reject corrupt batches, no silent overwrite | unit | `uv run pytest -q tests/test_quality_gates.py` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | DATA-02 | T-2-01 | no fabricated OI values, gaps journaled | unit | `uv run pytest -q tests/test_collector.py` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 1 | DATA-03 | — | metadata versioned from live exchangeInfo | unit | `uv run pytest -q tests/test_metadata.py` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 1 | DATA-04 | T-2-02 | restore verifies row-count/hash equality | integration | `powershell ./scripts/backup-drill.ps1` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_quality_gates.py` — stubs for DATA-01
- [ ] `tests/test_collector.py` — stubs for DATA-02
- [ ] `tests/test_metadata.py` — stubs for DATA-03
- [ ] `tests/conftest.py` — shared fixtures (golden exchangeInfo sample, kline fixtures)
- [ ] `pyproject.toml + uv.lock` — if no framework detected

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Off-host backup copy exists outside primary host | DATA-04 | target is operator-specific (OneDrive vs external) | Confirm backup artifact listed in off-host location after drill |
| 5-min OI cadence sustained 24h without gap storm | DATA-02 | wall-clock observation | Check watermark + gap journal after 24h run |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
