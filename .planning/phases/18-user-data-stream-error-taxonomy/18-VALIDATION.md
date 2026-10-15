---
phase: "18"
slug: user-data-stream-error-taxonomy
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-15"
---

# Phase 18 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 18-RESEARCH.md "Validation Architecture". Execution runs on a connected machine (user rule, 2026-10-15); this machine only plans and verifies plans.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with pytest-asyncio 1.4 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest -m "not docker" tests/<touched_file>.py -x` |
| **Full suite command** | `uv run pytest -m "not docker"` |
| **Other gates** | `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check` |
| **Live-PostgreSQL tests** | need `TEST_DATABASE_URL`; skip without it (G4-043 and G4-034 store tests) |
| **Estimated runtime** | quick: under 30 s per file; full suite: see Phase 17 baseline |

---

## Sampling Rate

- **After every task commit:** the touched test file(s) with `-x`, then `uv run ruff check` and `uv run mypy src` on the touched modules.
- **After every plan wave:** `uv run pytest -m "not docker"`, `uv run ruff format --check`, `uv lock --check`.
- **Before `/gsd-verify-work`:** full suite green and the blocking-human evidence files attached.
- **Max feedback latency:** one test file per task.

---

## Per-Task Verification Map

Task IDs are assigned by the planner; this map is completed from the PLAN files. Requirement-level mapping:

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| EXEC-05 | stream events become fills and state hints with REST fallback; replay, reorder and duplicate stay idempotent | unit + fake rig + replay | `uv run pytest -m "not docker" tests/test_userdata_events.py tests/test_userdata_supervisor.py tests/test_userdata_replay.py -x` | Wave 0 gap |
| EXEC-01 | algo status table drives attach and adoption; placement is never retried | unit | `uv run pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py -x` | partial |
| EXEC-02 | not-found and rate-limit handling in probes and the sweeper; evidence source recorded | unit | `uv run pytest -m "not docker" tests/test_exchange_errors.py tests/test_reconcile.py -x` | partial |
| OPS-02 | no secret, signature or listenKey in any output | unit | `uv run pytest -m "not docker" tests/test_binance_secret_redaction.py tests/test_binance_client_config.py -x` | Wave 0 gap |

---

## Wave 0 Requirements

- [ ] `tests/userdata_fakes.py` - SDK-shaped fake streams client and handle, mirrored by `tests/test_userdata_contract.py` (precedent: `paper_ws_fakes.py` and `test_paper_ws_contract.py`)
- [ ] `tests/fixtures/phase18/` - frames labelled `SYNTHETIC_FROM_SDK_MODEL`, replaced or complemented by `RECORDED_DEMO` frames after the probe
- [ ] every new test file named in the plans
- [ ] no framework install needed

---

## Manual-Only Verifications (blocking-human, connected machine)

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| O-18-01 ratification of safety numbers | OPS-02, EXEC-05 | owner-only (D061 H and I) | user fills the value column of the ratification table and records the decision file |
| Documentation re-read of the four event pages | EXEC-05 | this machine cannot fetch them | executor repeats the reads, updates the Phase 18 SOURCES section, records failures verbatim |
| Live Demo smoke (acceptance a to h in 18-RESEARCH.md) | EXEC-05, OPS-02 | needs Binance Demo keys and network | run the smoke script on the connected machine with Demo keys in the shell session |
| Probe `--execute` (D-16 cases) | EXEC-01, EXEC-02 | needs Binance Demo and the user typing the confirmation phrase | run the probe script; cleanup leaves zero open orders, zero open algo orders, flat position |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency within one test file per task
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
