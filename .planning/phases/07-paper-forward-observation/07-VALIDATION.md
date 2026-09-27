---
phase: "7"
slug: "paper-forward-observation"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: false
wave_0_complete: true
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

> Refreshed 2026-09-27 (Nyquist adversarial validation): the pre-execution
> map below referenced obsolete task IDs (7-01-01..7-03-01, plans 01-03)
> and omitted 07-04 freeze/notify coverage. This map now cross-references
> every requirement to its test file(s), including the REVIEW-FIX pins.

| Task ID | Plan | Requirement | Secure Behavior | Test Type | Automated Command | Status |
|---------|------|-------------|-----------------|-----------|-------------------|--------|
| 7-01-T1 | 01 | PAPER-01 | Closed-candle-only evaluation (forming + future-close ignored) | unit + golden fixture | `uv run pytest tests/test_paper_closed_candle.py -x` | ✅ green |
| 7-01-T2 | 01 | PAPER-01 | Warm-up invalid → NO_TRADE; stale feed → NO_TRADE + reason; recovery resumes | unit + golden fixture | `uv run pytest tests/test_paper_feed_gates.py -x` | ✅ green |
| 7-02-T1 | 02 | PAPER-01 | Reconnect + REST resync + gap journaled, nothing synthesized | unit + golden fixture | `uv run pytest tests/test_paper_resync.py -x` | ✅ green |
| 7-02-T2 | 02 | PAPER-01 | Rotation scheduled / disconnect resyncs / per-symbol isolation | unit (fakes) | `uv run pytest tests/test_paper_resync.py -x` | ✅ green |
| 7-02-T3 | 02 | PAPER-01 | Backtest↔paper parity on overlapping history (digest-exact) | golden fixture (byte-exact) | `uv run pytest tests/test_paper_parity.py -x` | ✅ green |
| 7-03-T1 | 03 | PAPER-02 | Three-way attribution + full timestamp lineage on every record | unit + golden fixture | `uv run pytest tests/test_paper_attribution.py -x` | ✅ green |
| 7-03-T2 | 03 | PAPER-02 | Skipped/expired plans retained with reason codes (never dropped) | unit | `uv run pytest tests/test_paper_attribution.py -x` | ✅ green |
| 7-04-T2 | 04 | PAPER-03 (D-04) | Registry diff opens new epoch; evidence windows per-epoch | unit + golden fixture | `uv run pytest tests/test_paper_freeze.py -x` | ✅ green |
| 7-04-T3 | 04 | PAPER-03 (D-05) | SIMULATE notify journal-first, 12 APRV-01 fields, inert callbacks | unit (fake bot) | `uv run pytest tests/test_paper_notify.py -x` | ✅ green |
| FIX-CR01 | review-fix | PAPER-01 | Pagination past 1500-row cap; ValueError fails fast (WR-02) | unit (paginating fake) | `uv run pytest tests/test_paper_reviewfix_pins.py -x` | ✅ green |
| FIX-CR02 | review-fix | PAPER-01 | Reconnect exhaustion still runs REST backfill, never raises | unit (failing WS fake) | `uv run pytest tests/test_paper_supervisor_backfill.py -x` | ✅ green |
| FIX-CR03 | review-fix | PAPER-01 | Backfilled closes returned per pair; missing last-close loud ERROR | unit (fakes + log spy) | `uv run pytest tests/test_paper_supervisor_backfill.py -x` | ✅ green |
| FIX-CR04 | review-fix | PAPER-01 | connect() delegates/raises; lifecycle fail-loud; attr-model coercion | unit (fake client/handles) | `uv run pytest tests/test_paper_ws_connect.py -x` | ✅ green |
| FIX-CR05 | review-fix | PAPER-03 (D-05) | callback_data within 64 bytes for real-length signal ids | unit | `uv run pytest tests/test_paper_reviewfix_pins.py -x` | ✅ green |
| FIX-CR07 | review-fix | PAPER-03 (D-05) | on_outcome outside retry; malformed payload FAILED attempts=0; root-cause error class | unit (counting bot) | `uv run pytest tests/test_paper_reviewfix_pins.py -x` | ✅ green |
| FIX-CR08 | review-fix | PAPER-01 | 4h closes route as CONTEXT_BAR, never as 1h setup bars | unit (fixture + 4h event) | `uv run pytest tests/test_paper_reviewfix_pins.py -x` | ✅ green |
| FIX-WR10 | review-fix | PAPER-01 | Full per-bar projection non-vacuous (narrow < full, signal-less present) | unit (replay both projections) | `uv run pytest tests/test_paper_reviewfix_pins.py -x` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Requirement → Test-File Cross-Reference (PAPER-03 / D-04 / D-05)

| Requirement | Test file(s) |
|-------------|--------------|
| PAPER-01 (realtime tick, resync, parity) | tests/test_paper_closed_candle.py, tests/test_paper_feed_gates.py, tests/test_paper_resync.py, tests/test_paper_parity.py, tests/test_paper_ws_connect.py, tests/test_paper_supervisor_backfill.py, tests/test_paper_reviewfix_pins.py |
| PAPER-02 (attribution journaling) | tests/test_paper_attribution.py |
| PAPER-03 / D-04 (freeze, pinned epoch, diff log) | tests/test_paper_freeze.py |
| PAPER-03 / D-05 (SIMULATE notify, journal-first) | tests/test_paper_notify.py, tests/test_paper_reviewfix_pins.py (CR-05/CR-07 pins) |

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
| WS live subscribe-against-connection smoke | PAPER-01 (CR-04 residual) | Needs real Binance WS stream; unit tests use injected fakes | Subscribe one Live-5 1H stream live 30s; expect ~120 events; record in soak log. Soak must not start until PASS |
| Simulator-side per-bar strategy outcomes for full cross-side parity | PAPER-01 (WR-10 residual) | Simulator emits trades only; per-bar outcomes are engine work, not a paper call-site fix | Engine extension + cross-side equality test; until then the paper-side full projection + anti-vacuity pin stands |
| Caller-side conversion of returned REST klines into loop feed_events | PAPER-01 (CR-03 residual) | Future wiring: returns are available per pair; the feed_events producer is not yet wired | Wire caller + integration test feeding backfilled closes through run_paper_tick |
| CONTEXT_BAR as downstream journal vocabulary | PAPER-02 (CR-08 residual) | Unit test pins emission; journal consumer acceptance is human | Confirm CONTEXT_BAR fits the JournalEvent reason vocabulary before soak |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 300s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---

## Validation Audit 2026-09-27
| Metric | Count |
|--------|-------|
| Gaps found | 6 |
| Resolved | 6 |
| Escalated | 0 (4 residuals recorded manual-only with reason, not escalations) |

- New tests: 23 (test_paper_ws_connect.py 9, test_paper_supervisor_backfill.py 5, test_paper_reviewfix_pins.py 9) — 23/23 green, ruff clean.
- Full paper suite: 69/69 green across 10 files (46 pre-existing + 23 new).
- Outcome: PARTIAL — all executable requirements automated; 6 manual-only rows (2 pre-existing wall-clock/creds + 4 review-fix residuals: WS-live smoke, simulator per-bar outcomes, REST→feed_events caller wiring, CONTEXT_BAR journal vocabulary).
