---
phase: "2"
slug: "data-foundation"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-09-19"
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio (auto mode) |
| **Config file** | pyproject.toml (`[tool.pytest.ini_options]`, asyncio_mode auto) |
| **Quick run command** | `uv run pytest -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~13 seconds (82 passed in 12.82s, 2026-09-22) |

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
| 02-01-01 | 01 | 1 | DATA-02, DATA-03 | T-02-01 | no archived connectors, SDK pinned >=17.3,<18 | unit | `uv run python --version` + `uv run pytest tests/test_wave0_sanity.py -q` | ✅ | ✅ green |
| 02-01-02 | 01 | 1 | DATA-02, DATA-03 | — | checkpoint: partition layout + PG split + PG17 hosting approved on record | checkpoint | `Test-Path .planning/phases/02-data-foundation/02-01-PLAN.md` | ✅ | ✅ green |
| 02-01-03 | 01 | 1 | DATA-02, DATA-03 | T-02-02 | credentials from env only, 4 tables TIMESTAMPTZ+NUMERIC | integration | `uv run pytest tests/ -q --collect-only` + `uv run python scripts/check_migration_parity.py` | ✅ | ✅ green |
| 02-02-01 | 02 | 2 | DATA-01 | T-02-03 | corrupt batches rejected, no overwrite | tracer | `uv run python -m src.data.coverage --symbol BTCUSDT` | ✅ | ✅ green |
| 02-02-02 | 02 | 2 | DATA-01 | T-02-03, T-02-04 | forming-candle drop, dedupe, 429-retry | unit | `uv run pytest tests/test_tracer_slice.py -q` (4 passed) | ✅ | ✅ green |
| 02-03-01 | 03 | 3 | DATA-01 | T-02-05 | reject corrupt batches, no silent overwrite | unit | `uv run pytest tests/test_quality_gates.py -q` (9 passed) | ✅ | ✅ green |
| 02-03-02 | 03 | 3 | DATA-01 | T-02-05 | cursor resume, corrupt-page fail-closed | unit | `uv run pytest tests/test_backfill.py -q` (5 passed) | ✅ | ✅ green |
| 02-04-01 | 04 | 3 | DATA-03 | T-02-07, T-02-08 | metadata versioned from live exchangeInfo, Decimal-exact | unit | `uv run pytest tests/test_metadata.py -q` (5 passed) | ✅ | ✅ green |
| 02-04-02 | 04 | 3 | DATA-02 | T-02-07 | no fabricated OI values, gaps journaled | unit | `uv run pytest tests/test_collector.py -q` (15 passed) | ✅ | ✅ green |
| 02-05-01 | 05 | 4 | DATA-01 | — | range + gap/violation counts per live-5×interval, HCMC edge only | unit | `uv run pytest tests/test_coverage.py -q` (17 passed) | ✅ | ✅ green |
| 02-05-02 | 05 | 4 | DATA-04 | T-02-09 | checkpoint: off-host target confirmed (OneDrive-synced dir) | checkpoint | `Test-Path $env:BACKUP_TARGET` | ✅ | ✅ green |
| 02-05-03 | 05 | 4 | DATA-04 | T-02-09, T-02-10 | restore verifies sha256 + row-count equality, tamper exits non-zero | unit+integration | `uv run pytest tests/test_backup.py -q` (19 passed) + `powershell ./scripts/backup-drill.ps1` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

Requirement → test-file cross-reference (2026-09-22 audit):
- DATA-01 → test_tracer_slice.py (4) + test_quality_gates.py (9) + test_backfill.py (5) + test_coverage.py (17) + test_adapter_strictness.py (5, boundary guard) — COVERED, green
- DATA-02 → test_collector.py (15) — COVERED, green
- DATA-03 → test_metadata.py (5) — COVERED, green
- DATA-04 → test_backup.py (19) — COVERED, green
- Full suite: 82 passed (test_wave0_sanity 3 + above 77 + 2 parity-adjacent), `ruff check` clean

---

## Wave 0 Requirements

- [x] `tests/test_quality_gates.py` — DATA-01 quality verdict (9 tests, green)
- [x] `tests/test_collector.py` — DATA-02 OI/funding collector (15 tests, green)
- [x] `tests/test_metadata.py` — DATA-03 versioned metadata (5 tests, green)
- [x] `tests/conftest.py` — shared fixtures (golden exchangeInfo sample, kline fixtures)
- [x] `pyproject.toml + uv.lock` — framework present (pytest 9.1.1, asyncio auto mode)

*Existing infrastructure covers all phase requirements — no Wave 0 stubs remain.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Off-host backup copy exists outside primary host | DATA-04 | target is operator-specific (OneDrive vs external) | Confirm backup artifact listed in off-host location after drill |
| 5-min OI cadence sustained 24h without gap storm | DATA-02 | wall-clock observation | Check watermark + gap journal after 24h run |

Env-gated operator close-outs (have automated unit coverage; need live Docker PG17 + network — see 02-VERIFICATION.md Human Verification, NOT Nyquist gaps):
- Boot PG + `alembic upgrade head` live · First live bounded bootstrap + coverage query · Deploy OI/funding loop 2–3 ticks · Live-PG backup drill

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s (~13s full suite)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-09-22

## Validation Audit 2026-09-22

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Audit note: seeded VALIDATION.md (2026-09-19 draft) listed 4 stale rows (❌ W0, ⬜ pending). Post-execution audit found 12/12 tasks with automated verify, 82/82 tests green, `ruff check` clean — no COVERED/PARTIAL/MISSING gaps. Update refreshes the Per-Task Map (4→12 rows), Test Infrastructure (config: none → pyproject.toml, runtime ~13s), Wave 0 checkboxes, and frontmatter (`status: validated`, `nyquist_compliant: true`, `wave_0_complete: true`). No auditor spawn needed (skip §4–§5 per workflow: no gaps → §6).
