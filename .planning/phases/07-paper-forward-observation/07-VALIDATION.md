---
phase: "7"
slug: "paper-forward-observation"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-26"
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `07-RESEARCH.md` § Validation Architecture (verified: pyproject.toml
> `asyncio_mode = "auto"`, `testpaths = ["tests"]`, pytest 9 + pytest-asyncio).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9 + pytest-asyncio (auto mode) |
| **Config file** | pyproject.toml (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| **Quick run command** | `uv run pytest tests/test_paper_<slice>.py -x` |
| **Full suite command** | `uv run pytest -x` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_paper_<slice>.py -x` + `ruff check` + `mypy` on touched package
- **After every plan wave:** Run `uv run pytest -x` (full suite green — backtest↔paper parity must never regress)
- **Before `/gsd-verify-work`:** Full suite green + parity fixtures byte-exact
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 7-01-01 | 01 | 1 | PAPER-01 | — | Closed-candle-only evaluation (forming updates ignored) | unit | `uv run pytest tests/test_paper_closed_candle.py -x` | ❌ W0 | ⬜ pending |
| 7-01-02 | 01 | 1 | PAPER-01 | — | Reconnect + REST resync + gap journaled, nothing synthesized | unit + golden fixture | `uv run pytest tests/test_paper_resync.py -x` | ❌ W0 | ⬜ pending |
| 7-01-03 | 01 | 1 | PAPER-01 | T-7-01 | Warm-up invalid → NO_TRADE; stale feed → NO_TRADE + reason | unit | `uv run pytest tests/test_paper_feed_gates.py -x` | ❌ W0 | ⬜ pending |
| 7-02-01 | 02 | 2 | PAPER-01 | — | Backtest↔paper parity on overlapping history (no material divergence) | golden fixture (byte-exact) | `uv run pytest tests/test_paper_parity.py -x` | ❌ W0 | ⬜ pending |
| 7-02-02 | 02 | 2 | PAPER-02 | T-7-02 | Three-way attribution + full timestamp lineage on every record | unit + golden fixture | `uv run pytest tests/test_paper_attribution.py -x` | ❌ W0 | ⬜ pending |
| 7-02-03 | 02 | 2 | PAPER-02 | — | Skipped/expired plans retained with reason codes (never dropped) | unit | `uv run pytest tests/test_paper_attribution.py -x` | ❌ W0 | ⬜ pending |
| 7-03-01 | 03 | 2 | PAPER-03 | T-7-03 | Registry diff opens new epoch; evidence windows per-epoch | unit | `uv run pytest tests/test_paper_freeze.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/fixtures/phase7/` — feed sequences (clean run, reconnect+resync, unrecoverable gap, epoch rollover) + expected journal/attribution/epoch records, byte-exact
- [ ] `tests/test_paper_closed_candle.py`, `test_paper_resync.py`, `test_paper_feed_gates.py`, `test_paper_parity.py`, `test_paper_attribution.py`, `test_paper_freeze.py` — cover PAPER-01..03 per map above
- [ ] `src/paper/` package skeleton (dependency-free) + `src/adapters/paper_ws.py` edge — needed before any RED test can import
- [ ] Framework install: `uv add "python-telegram-bot>=22.8,<23"` behind `checkpoint:human-verify` — before notify tests

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 3–6-month soak envelope + no-unexplained-gaps | PAPER-03 | Wall-clock cannot be unit-tested | Runbook exercise + registry diff-log review at soak checkpoints |
| Pre-soak smoke: PG-17 reachable, Telegram token/chat live, Binance reachable | PAPER-01 | Operational credentials outside test sandbox | Run pre-soak smoke task; record results in soak log |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
