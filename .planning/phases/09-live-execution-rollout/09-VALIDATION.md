---
phase: "9"
slug: "live-execution-rollout"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-28"
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `09-RESEARCH.md` § Validation Architecture (verified: pyproject.toml
> `asyncio_mode = "auto"`, `testpaths = ["tests"]`, pytest ≥ 9 + pytest-asyncio,
> SDK 17.4.0 introspected this session).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥ 9 + pytest-asyncio (auto mode) |
| **Config file** | pyproject.toml (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| **Quick run command** | `uv run --python 3.13 pytest tests/ -q -x` |
| **Full suite command** | `uv run --python 3.13 pytest tests/ -q` (+ `ruff check` + `mypy src` per AGENTS.md) |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run --python 3.13 pytest tests/ -q -x`
- **After every plan wave:** Run full suite + `ruff check` + `mypy src`
- **Before `/gsd-verify-work`:** Full suite green + testnet placement rehearsal
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 9-0X-01 | TBD | TBD | EXEC-01 | — | LIMIT entry + CONDITIONAL protectives placed with deterministic IDs (fake adapter) | unit | `uv run --python 3.13 pytest tests/test_execution_manager.py -x -q` | ❌ W0 | ⬜ pending |
| 9-0X-02 | TBD | TBD | EXEC-01 | — | Both position-mode branches (one-way close-all vs hedge explicit side) | unit | `uv run --python 3.13 pytest tests/test_execution_modes.py -x -q` | ❌ W0 | ⬜ pending |
| 9-0X-03 | TBD | TBD | EXEC-01 | — | Protectives sized to filled qty on partials; idempotent retry/restart | unit | `uv run --python 3.13 pytest tests/test_execution_partials.py -x -q` | ❌ W0 | ⬜ pending |
| 9-0X-04 | TBD | TBD | EXEC-01 | — | Headroom reject + no-blind-recovery query-by-ID | unit | `uv run --python 3.13 pytest tests/test_execution_gates.py -x -q` | ❌ W0 | ⬜ pending |
| 9-0X-05 | TBD | TBD | OPS-02 | — | `LIVE_ORDERS_DISABLED` default; enablement + emergency controls; secret-free logs | unit | `uv run --python 3.13 pytest tests/test_execution_enablement.py -x -q` | ❌ W0 | ⬜ pending |
| 9-0X-06 | TBD | TBD | OPS-02 | — | DAILY_STOP on live reconciled state; stale snapshot fail-closed | unit | `uv run --python 3.13 pytest tests/test_execution_gates.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/fixtures/phase9/` — placement sequences, partial-fill sizing, mode branches, retry/headroom/DAILY_STOP rejects (byte-exact golden files)
- [ ] `tests/test_execution_*.py` — manager, modes, partials, gates, enablement suites (names at planner discretion)
- [ ] Testnet rehearsal task — real LIMIT + CONDITIONAL round-trip on smallest qty before live enablement
- [ ] 08-02 LIVE-TAP GATE clearance (Telegram token + chat) — prerequisite for live acceptance

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Testnet LIMIT + CONDITIONAL round-trip on smallest qty | EXEC-01 | Real exchange round-trip outside unit sandbox | `checkpoint:human-verify` before live-enablement task; operator runs rehearsal on testnet, confirms entry + both protective legs + fills reconcile |
| LIVE-TAP GATE clearance + live credential provisioning (no-withdrawal + allowlist) | OPS-02 | Operator-provisioned credentials outside test sandbox | `checkpoint:human-verify`; operator provisions keys + Telegram token/chat, confirms health checklist green before first order |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
