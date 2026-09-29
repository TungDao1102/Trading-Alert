---
phase: "10"
slug: "journal-depth-kill-gate-operations"
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-29"
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: `10-RESEARCH.md` § Validation Architecture. Task IDs below are the real plan/task ids from the 12 phase plans (`10-NN-MM` = plan NN, task MM).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 9 + pytest-asyncio (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, mypy strict, ruff line-length 100) |
| **Quick run command** | `uv run --python 3.13 pytest tests/test_analytics_*.py tests/test_kill_gate*.py -x -q` |
| **Full suite command** | `uv run --python 3.13 pytest -q` (or `scripts/dev/test.ps1`); baseline before this phase was fully green (~2.5 min) |
| **Static gates** | `tests/test_analytics_typing.py` (mypy strict on `src/analytics` and the two analytics adapters, filtered by path because one pre-existing mypy error exists in `src/adapters/telegram_notify.py`), `uv run --python 3.13 ruff check <phase-10 files>` (repo-wide ruff has 24 pre-existing findings, so it is scoped), `uv run --python 3.13 python scripts/check_migration_parity.py` |
| **Estimated runtime** | quick ~10-20 s; full suite ~2.5-3 min |

---

## Sampling Rate

- **After every task commit:** run the task's own `<automated>` command (listed below) plus `uv run --python 3.13 pytest tests/test_analytics_purity.py tests/test_analytics_typing.py -q` once `src/analytics` exists
- **After every plan wave:** run the quick command, then `uv run --python 3.13 pytest -q`
- **Before `/gsd-verify-work`:** full suite green + migration parity green
- **Max feedback latency:** 60 seconds (quick run)

---

## Per-Task Verification Map

Test files and fixtures are created inside each plan's RED step (TDD), so "File Exists" is `❌ W0` until the owning task runs.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | JRN-01 | T-10-02 | tracer: one LONG trade -> MFE/MAE price+R, pinned digest | tracer + golden | `uv run --python 3.13 pytest tests/test_analytics_excursion.py -x -q -k tracer` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | JRN-01 | T-10-02 | SHORT, zero-risk excluded+counted, INCOMPLETE never imputed, bootstrap aggregates | unit + golden | `uv run --python 3.13 pytest tests/test_analytics_excursion.py tests/test_analytics_incomplete.py -x -q` | ❌ W0 | ⬜ pending |
| 10-01-03 | 01 | 1 | JRN-01 | T-10-01, T-10-03 | byte-identical digest regeneration; purity/no-float/typing guards | determinism + static | `uv run --python 3.13 pytest tests/test_analytics_digest.py tests/test_analytics_purity.py tests/test_analytics_typing.py -x -q` | ❌ W0 | ⬜ pending |
| 10-02-01 | 02 | 1 | GOV-01 | T-10-04, T-10-05 | D030 row + protocol v1.0.1; freeze witnesses intact | doc-parity | `uv run --python 3.13 pytest tests/test_kill_gate_docs.py -x -q` | ❌ W0 | ⬜ pending |
| 10-02-02 | 02 | 1 | GOV-01 | T-10-06 | KillGateState enum equals GLOSSARY 8.2 | unit + doc-parity | `uv run --python 3.13 pytest tests/test_domain_enums.py tests/test_kill_gate_docs.py tests/test_domain_no_float.py -x -q` | ⚠ extend + W0 | ⬜ pending |
| 10-03-01 | 03 | 2 | JRN-01 | T-10-07 | tracer: paper lifecycle -> six legs, synthetic-lag label | tracer + golden | `uv run --python 3.13 pytest tests/test_analytics_latency.py -x -q -k tracer` | ❌ W0 | ⬜ pending |
| 10-03-02 | 03 | 2 | JRN-01 | T-10-07 | fill %, wait-to-fill, expiry rate, signed entry deviation | unit + golden | `uv run --python 3.13 pytest tests/test_analytics_latency.py tests/test_analytics_lifecycle.py -x -q` | ❌ W0 | ⬜ pending |
| 10-03-03 | 03 | 2 | JRN-01 | T-10-08, T-10-09 | live joins matched/unmatched/rejected; malformed payload counted | unit + golden | `uv run --python 3.13 pytest tests/test_analytics_lifecycle.py tests/test_analytics_latency.py -x -q` | ❌ W0 | ⬜ pending |
| 10-04-01 | 04 | 2 | JRN-01 | T-10-10 | tracer: core metrics + symbol slice, ALL row first, low-n kept | tracer + golden | `uv run --python 3.13 pytest tests/test_analytics_slices.py -x -q -k tracer` | ❌ W0 | ⬜ pending |
| 10-04-02 | 04 | 2 | JRN-01 | T-10-10 | eight slice dimensions, pinned time bases, stable ordering | unit + golden | `uv run --python 3.13 pytest tests/test_analytics_slices.py -x -q` | ❌ W0 | ⬜ pending |
| 10-04-03 | 04 | 2 | JRN-01, GOV-01 | T-10-11, T-10-12 | empty live-5 = no data; UNMAPPED NO_TRADE bucket; evidence unpooled | unit | `uv run --python 3.13 pytest tests/test_analytics_dual_universe.py tests/test_analytics_no_trade.py -x -q` | ❌ W0 | ⬜ pending |
| 10-05-02 | 05 | 2 | GOV-01 | T-10-13, T-10-16 | tracer: evaluate() -> verdict + KILL_GATE_EVALUATION event (task 10-05-01 is the pre-approved decision checkpoint) | tracer + golden | `uv run --python 3.13 pytest tests/test_kill_gate_state.py tests/test_kill_gate_event.py -x -q -k tracer` | ❌ W0 | ⬜ pending |
| 10-05-03 | 05 | 2 | GOV-01 | T-10-14, T-10-15 | 6-month boundary, PASSING_CANDIDATE, independence, input validation, secret-free payload | unit + golden | `uv run --python 3.13 pytest tests/test_kill_gate_state.py tests/test_kill_gate_families.py tests/test_kill_gate_event.py -x -q` | ❌ W0 | ⬜ pending |
| 10-06-01 | 06 | 3 | JRN-01 | T-10-18 | tracer: System/User/Opportunity side by side; synthetic-lag label | tracer + golden | `uv run --python 3.13 pytest tests/test_analytics_approval_delay.py -x -q -k tracer` | ❌ W0 | ⬜ pending |
| 10-06-02 | 06 | 3 | JRN-01 | T-10-18, T-10-19 | LIVE-only delay buckets; paper constant unchanged | unit | `uv run --python 3.13 pytest tests/test_analytics_approval_delay.py -x -q` | ❌ W0 | ⬜ pending |
| 10-06-03 | 06 | 3 | JRN-01 | T-10-17 | live net R behind verified-or-fail-closed exchange semantics | unit + golden | `uv run --python 3.13 pytest tests/test_analytics_live_outcomes.py -x -q` | ❌ W0 | ⬜ pending |
| 10-07-01 | 07 | 3 | GOV-01 | T-10-21 | tracer: sticky terminal; reset only by explicit human event; replay idempotent | tracer + unit | `uv run --python 3.13 pytest tests/test_kill_gate_sticky.py -x -q` | ❌ W0 | ⬜ pending |
| 10-07-02 | 07 | 3 | GOV-01 | T-10-23 | clock start from protocol header (CI regex); gate cells never fabricate a pass | unit | `uv run --python 3.13 pytest tests/test_kill_gate_clock.py tests/test_kill_gate_gates.py -x -q` | ❌ W0 | ⬜ pending |
| 10-07-03 | 07 | 3 | GOV-01 | T-10-20, T-10-22 | enable() refuses INSUFFICIENT_EDGE before journaling; registration tripwire | unit + doc-parity | `uv run --python 3.13 pytest tests/test_execution_enablement.py tests/test_execution_health.py tests/test_execution_manager.py tests/test_kill_gate_registration.py -x -q` | ⚠ extend + W0 | ⬜ pending |
| 10-08-01 | 08 | 4 | JRN-01 | T-10-27 | tracer: three evidence blocks + report digest | tracer + golden | `uv run --python 3.13 pytest tests/test_analytics_report.py -x -q -k tracer` | ❌ W0 | ⬜ pending |
| 10-08-02 | 08 | 4 | JRN-01, GOV-01 | T-10-25 | provenance, INCOMPLETE ledger, live posture, kill-gate section | unit | `uv run --python 3.13 pytest tests/test_analytics_report.py tests/test_analytics_provenance.py -x -q` | ❌ W0 | ⬜ pending |
| 10-08-03 | 08 | 4 | JRN-01 | T-10-24, T-10-26 | evidence never pooled; order-independent digest; secret-free | unit + determinism | `uv run --python 3.13 pytest tests/test_analytics_report.py tests/test_analytics_provenance.py -x -q` | ❌ W0 | ⬜ pending |
| 10-09-01 | 09 | 4 | GOV-01 | T-10-32 | tracer: real-repo family scan feeds the evaluator | tracer | `uv run --python 3.13 pytest tests/test_analytics_files.py -x -q -k "tracer or scan"` | ❌ W0 | ⬜ pending |
| 10-09-02 | 09 | 4 | JRN-01, GOV-01 | T-10-29, T-10-30 | fail-closed loaders; output-path confinement | unit | `uv run --python 3.13 pytest tests/test_analytics_files.py -x -q` | ❌ W0 | ⬜ pending |
| 10-09-03 | 09 | 4 | JRN-01, GOV-01 | T-10-28, T-10-31 | SELECT-only reader; guarded idempotent append; candle reader; no migration | unit + script | `uv run --python 3.13 pytest tests/test_analytics_store.py -x -q` then `uv run --python 3.13 python scripts/check_migration_parity.py` | ❌ W0 | ⬜ pending |
| 10-10-01 | 10 | 5 | GOV-01 | T-10-33, T-10-36 | tracer: md_cell escaping, pinned number formats, header + banner + budget + clock | tracer + unit | `uv run --python 3.13 pytest tests/test_analytics_render.py -x -q -k "primitives or header or banner or budget or clock or tracer"` | ❌ W0 | ⬜ pending |
| 10-10-02 | 10 | 5 | JRN-01, GOV-01 | T-10-34, T-10-35 | K-2/K-3, decisions, Evidence Overview; INSUFFICIENT_EDGE rendered as terminal | golden | `uv run --python 3.13 pytest tests/test_analytics_render.py -x -q` | ❌ W0 | ⬜ pending |
| 10-11-01 | 11 | 6 | JRN-01 | T-10-39 | tracer: sections 3-4 (M-1, U-1), no bare numbers | tracer + unit | `uv run --python 3.13 pytest tests/test_analytics_render.py -x -q -k "section3 or section4 or full_report or dual_universe or tracer"` | ❌ W0 | ⬜ pending |
| 10-11-02 | 11 | 6 | JRN-01 | T-10-39 | sections 5-10 + full Markdown golden | golden | `uv run --python 3.13 pytest tests/test_analytics_render.py -x -q` | ❌ W0 | ⬜ pending |
| 10-11-03 | 11 | 6 | JRN-01, GOV-01 | T-10-37, T-10-38, T-10-40 | JSON sidecar digests verify; secret/path scans; pointer is decision-free | golden + scan | `uv run --python 3.13 pytest tests/test_analytics_sidecar.py tests/test_analytics_render.py -x -q` | ❌ W0 | ⬜ pending |
| 10-12-01 | 12 | 7 | JRN-01, GOV-01 | T-10-41, T-10-45 | tracer: CLI end to end, byte-identical files, exit codes | tracer + golden | `uv run --python 3.13 pytest tests/test_analytics_cli.py -x -q -k "not record and not db"` | ❌ W0 | ⬜ pending |
| 10-12-02 | 12 | 7 | GOV-01 | T-10-42, T-10-43, T-10-44 | read-only DB path; --record idempotent; no URL leak | unit | `uv run --python 3.13 pytest tests/test_analytics_cli.py -x -q` | ❌ W0 | ⬜ pending |
| 10-12-03 | 12 | 7 | JRN-01, GOV-01 | T-10-46 | wrapper, SCANNED_FILES drift guard, migration parity, full suite | static + regression | `uv run --python 3.13 pytest -q` then `uv run --python 3.13 python scripts/check_migration_parity.py` | ⚠ extend + W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is satisfied inside the plans: every test module and fixture below is created in the owning task's RED step before implementation (no separate scaffold plan).

- [ ] `tests/fixtures/phase10/` cases: `complete_trade`, `short_trade`, `zero_risk_excluded`, `incomplete_no_1m`, `incomplete_no_fill`, `digest_regeneration` (10-01); `paper_lifecycle`, `opportunity_skipped_expired`, `live_lifecycle` (10-03); `low_n_slices`, `empty_live5_slice`, `no_trade_categories` (10-04); `kill_within_budget`, `kill_insufficient_edge`, `kill_clock_boundary`, `kill_passing_candidate` (10-05); `approval_delay_three_reports`, `live_net_r` (10-06); `kill_sticky_reset`, `idempotent_replay`, `clock_start_provenance` (10-07); `report_composite` (10-08); `loaders/` (10-09); `render_golden/` (10-10, 10-11)
- [ ] `tests/test_analytics_*.py`, `tests/test_kill_gate_*.py` (list above)
- [ ] Extend `SCANNED_FILES` in `tests/test_domain_no_float.py` (plan 12, plus the glob-based purity guard from plan 01); update the 7 `.enable(` call sites (plan 07)
- [ ] `KillGateState` enum + verbatim enum test; GLOSSARY section 8.2 (plan 02)
- Framework install: none — pytest/mypy/ruff already present.

---

## Manual-Only Verifications

All phase behaviors have automated verification. The only human checks are the two UI-SPEC backstops (K-2b / S-1 table legibility in a plain terminal, Markdown-viewer rendering identity), recorded as a `<human-check>` in plan 11 task 3 and consolidated at end-of-phase. Human decision records for family PASS/FAIL and terminal-state reset are inputs the tests supply as fixtures, not manual steps of this phase.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
