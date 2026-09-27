---
phase: "8"
slug: "approval-reconciliation-hardening"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-27"
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `08-RESEARCH.md` § Validation Architecture (verified: pyproject.toml
> `asyncio_mode = "auto"`, `testpaths = ["tests"]`, pytest ≥ 9 + pytest-asyncio).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥ 9 + pytest-asyncio (auto mode) |
| **Config file** | pyproject.toml (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| **Quick run command** | `uv run pytest tests/ -x -q` |
| **Full suite command** | `uv run pytest tests/ -q` (+ `ruff check` + `mypy src` per AGENTS.md) |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_<module>.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite green + `ruff check` + `mypy src`
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 8-01-01 | 01 | 0 | — | — | SDK 17.3.1→17.4.0 changelog diff + signature re-check; OrderRole vocabulary freeze | manual review + unit | `uv run pytest tests/test_order_ids.py -x -q` | ✅ done | ✅ green |
| 8-0X-01 | 02 | 1 | APRV-01 | T-8-01 | APPROVE/SKIP message carries all 12 fields; callback_data ≤ 64 bytes | unit | `uv run pytest tests/test_approval_message.py -x -q` | ✅ done | ✅ green (29) |
| 8-0X-02 | 01 | 1 | APRV-02 | T-8-02 | 5× replay = exactly one transition; stale unapprovable with reason code; notify-failure stays PENDING | unit (golden replay) | `uv run pytest tests/test_approval_replay.py -x -q` | ✅ done | ✅ green (13) |
| 8-0X-03 | 04 | 2 | EXEC-02 | T-8-03 | Injected orphan swept; divergence forces SAFE_MODE; reconciler never places orders | unit + fake exchange | `uv run pytest tests/test_reconcile.py -x -q` | ✅ done | ✅ green (7) |
| 8-0X-04 | 03 | 2 | EXEC-03 | T-8-04 | Retry/restart/replay → identical client/algo IDs; role codes never collide | unit (determinism) | `uv run pytest tests/test_order_ids.py -x -q` | ✅ done | ✅ green (21) |
| 8-0X-05 | 05 | 3 | OPS-01 | — | All 8 drills rehearsed with injected faults; drill log journaled; SAFE_MODE exit via restore only | unit (drill harness) | `uv run pytest tests/test_drills.py -x -q` | ✅ done | ✅ green (9) |
| 8-audit | — | — | CR-01..CR-03 + WR-01..WR-31 (34 review fixes) | — | Each fixed behavior covered by at least one test (auditor-verified) | unit (audit) | `uv run pytest tests/test_phase8_audit_reviewfix.py -x -q` | ✅ done | ✅ green (58) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements — all delivered during execution

- [x] `tests/fixtures/phase8/` — replay sequences (5× duplicate callbacks), injected-orphan/divergence scenarios, retry/restart ID determinism vectors, drill-log goldens
- [x] `tests/test_approval_replay.py` — covers APRV-02 (13 tests)
- [x] `tests/test_approval_message.py` — covers APRV-01 (29 tests, extends Phase-7 notify goldens)
- [x] `tests/test_reconcile.py` — covers EXEC-02 (7 tests, fake three-source exchange adapter)
- [x] `tests/test_order_ids.py` — covers EXEC-03 (21 tests)
- [x] `tests/test_drills.py` — covers OPS-01 (9 tests)
- [x] Migration for short→full mapping table (`src/db/alembic/versions/0003_callback_mapping.py`, PG-backed mapping per planner choice)
- [x] SDK 17.3.1→17.4.0 changelog diff + signature re-check (Wave 0 prerequisite, done in 08-01)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Telegram callback delivery (token + authorized chat) | APRV-01 | Operator-provisioned credentials outside test sandbox | `checkpoint:human-verify` before live-wiring task; tap APPROVE/SKIP on a real message, confirm single transition |
| Live reconciler proof against Binance (read-only keys) | EXEC-02 | Operator-provisioned keys outside test sandbox | `checkpoint:human-verify`; recorded exchangeInfo/algo-order fixtures in unit tests, live read-only query in drill |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter — stays `false`: 2 manual-only live verifications outstanding (PARTIAL, same posture as Phase 7)

**Approval:** validated (PARTIAL — 137 automated green, 2 manual-only)

## Validation Audit 2026-09-28
| Metric | Count |
|--------|-------|
| Gaps found | 34 (review-fix behaviors without dedicated coverage proof) |
| Resolved | 34 (58 tests in `tests/test_phase8_audit_reviewfix.py`, all green) |
| Escalated | 0 (auditor used 3/3 debug iterations on test-side issues only; zero impl bugs) |

Full suite at audit close: 610 passed, 5 pre-existing skips. `ruff check` + `ruff format --check` clean on the new file. No `src/` modifications by the auditor.
Note: `DrillDeclaration` rejects non-canonical drill names — the WR-29 parallel-run claim holds for repeated canonical drills (documented single-writer scope).
