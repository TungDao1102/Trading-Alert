---
phase: "10"
slug: "journal-depth-kill-gate-operations"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-29"
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: `10-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 9 + pytest-asyncio (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, mypy strict, ruff line-length 100) |
| **Quick run command** | `uv run pytest tests/test_analytics_*.py tests/test_kill_gate*.py -x` |
| **Full suite command** | `scripts/dev/test.ps1` (wraps `uv run pytest`) or `uv run pytest` |
| **Static gates** | `uv run mypy src`, `uv run ruff check src tests`, `uv run python scripts/check_migration_parity.py` |
| **Estimated runtime** | quick ~10 s; full suite per `scripts/dev/test.ps1` timing output |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_analytics_*.py tests/test_kill_gate*.py -x` and `uv run mypy src/analytics`
- **After every plan wave:** Run `uv run pytest` + `uv run mypy src` + `uv run ruff check src tests`
- **Before `/gsd-verify-work`:** Full suite green + migration parity green
- **Max feedback latency:** 60 seconds (quick run)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-XX-XX | TBD | TBD | JRN-01 | T-10-XX | MFE/MAE price+R, zero-risk excluded+counted | unit + golden | `uv run pytest tests/test_analytics_excursion.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | T-10-XX | INCOMPLETE bucket, never imputed | unit + golden | `uv run pytest tests/test_analytics_incomplete.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | — | latency legs, fill %, wait-to-fill, expiry rate, entry deviation | unit + golden | `uv run pytest tests/test_analytics_latency.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | — | System/User/Opportunity side by side; synthetic-lag labelled | unit | `uv run pytest tests/test_analytics_approval_delay.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | — | seven slice dimensions, low-n flagged not hidden, full report alongside | unit + golden | `uv run pytest tests/test_analytics_slices.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | — | empty live-5 = "no data"; evidence kinds never pooled | unit | `uv run pytest tests/test_analytics_dual_universe.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | — | byte-identical digest regeneration | determinism | `uv run pytest tests/test_analytics_digest.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | JRN-01 | — | pure-module float/import guards | static | `uv run pytest tests/test_domain_no_float.py tests/test_analytics_purity.py -x` | ⚠ extend + W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | T-10-XX | WITHIN_BUDGET / PASSING_CANDIDATE / INSUFFICIENT_EDGE incl. 6-month boundary | unit + golden | `uv run pytest tests/test_kill_gate_state.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | T-10-XX | sticky terminal; reset only by explicit human event | unit | `uv run pytest tests/test_kill_gate_sticky.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | — | clock-start provenance from protocol header | unit | `uv run pytest tests/test_kill_gate_clock.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | — | independence: distinct strategy_id + template + sheet hash; baselines excluded | unit | `uv run pytest tests/test_kill_gate_families.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | T-10-XX | `KILL_GATE_EVALUATION` content-hash id, idempotent replay | unit | `uv run pytest tests/test_kill_gate_event.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | T-10-XX | `enable()` refuses on INSUFFICIENT_EDGE before journaling | unit | `uv run pytest tests/test_execution_enablement.py -x` | ⚠ extend | ⬜ pending |
| 10-XX-XX | TBD | TBD | GOV-01 | — | doc tripwire: D030 row, protocol `Frozen on` unchanged | doc-parity | `uv run pytest tests/test_kill_gate_docs.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | Both | T-10-XX | render byte-identity (Markdown + JSON sidecar), escaping, INSUFFICIENT_EDGE rendered as terminal | golden | `uv run pytest tests/test_analytics_render.py -x` | ❌ W0 | ⬜ pending |
| 10-XX-XX | TBD | TBD | Both | — | no migration: parity gate green | script | `uv run python scripts/check_migration_parity.py` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/fixtures/phase10/` cases: complete_trade, incomplete_no_fill, incomplete_no_1m, zero_risk_excluded, short_trade, empty_live5_slice, opportunity_skipped_expired, low_n_slices, kill_within_budget, kill_passing_candidate, kill_insufficient_edge, kill_clock_boundary, kill_sticky_reset, clock_start_provenance, idempotent_replay, digest_regeneration, render_golden
- [ ] `tests/test_analytics_*.py`, `tests/test_kill_gate_*.py` (list above)
- [ ] Extend `SCANNED_FILES` in `tests/test_domain_no_float.py`; update the 7 `.enable(` call sites
- [ ] `KillGateState` enum + verbatim enum test; GLOSSARY section
- Framework install: none — pytest/mypy/ruff already present.

---

## Manual-Only Verifications

All phase behaviors have automated verification. (Human decision records for family PASS/FAIL and terminal-state reset are inputs the tests supply as fixtures, not manual steps of this phase.)

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
