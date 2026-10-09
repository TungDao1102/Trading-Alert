---
phase: "16"
slug: paper-runtime-composition
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-08"
---

# Phase 16 — Validation Strategy

> Seeded from the "Validation Architecture" section of `16-RESEARCH.md`. Rows marked REV were added because RESEARCH predates REV-15..REV-18 (D065) and does not cover them. Plan/Task columns filled by the planner audit of 2026-10-08 (49 plans, 16-01..16-49; plan 16-50 was added on 2026-10-09, making 50 plans, 16-01..16-50, with its rows at the end of the map); rows below the first block were added for behaviours the plans introduce. Task ids read `16-NN Tn`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), respx 0.23.1 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, marker `docker`) |
| **Quick run command** | `PYTHONPATH=. uv run pytest tests/<file>.py -q -p no:cacheprovider` (the plans use the equivalent `.venv/Scripts/python -m pytest ...` on the Windows execution machine) |
| **Full suite command** | `uv run pytest -m "not docker" -rs -p no:cacheprovider` plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (CI: `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set) |
| **Estimated runtime** | measured at Wave 0; baseline 11 paper test files, 157 tests passed on 2026-10-07 |

---

## Sampling Rate

- **After every task commit:** the touched test files, one file per command on Windows
- **After every plan wave:** every `tests/test_paper_*.py` file one by one, plus ruff and mypy
- **Before `/gsd-verify-work`:** full CI-equivalent run with `TEST_DATABASE_URL` set, then the blocking-human evidence in "Manual-Only Verifications"
- **Max feedback latency:** set by the planner after the first measured quick run

---

## Per-Task Verification Map

Each row is a behavior with at least one task that has an `<automated>` command and a `<fails_when>`.

| Criterion | Plan/Task | Requirement | Behavior (secure/expected) | Test Type | Automated Command | File Exists | Status |
|-----------|-----------|-------------|----------------------------|-----------|-------------------|-------------|--------|
| SC1 composition | 16-22 T1, T3; 16-26 T1 | PAPER-01 | empty allowlist exits 0 `SKIPPED (allowlist empty)`; never subscribes; open candle never reaches the tick | unit | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_compose.py tests/test_paper_runtime_loop.py -q` | ❌ W0 | ⬜ pending |
| SC1 restart/gap | 16-29 T1, T2, T3 | PAPER-01 | downtime gap row; backfilled bars never evaluated; no duplicate signal, no missing journal row | integration (PG) | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_restart.py tests/test_paper_runtime_restart_pg.py -q` | ❌ W0 | ⬜ pending |
| SC1 resync | 16-08 T2 | PAPER-01 | close = open + interval - 1 ms gives zero phantom gaps | unit | `PYTHONPATH=. uv run pytest tests/test_paper_resync.py -q` | ✅ extend | ⬜ pending |
| SC2 contract | 16-01 T2 | PAPER-01 | fakes mirror the SDK async surface; sync fake fails (negative control) | unit | `PYTHONPATH=. uv run pytest tests/test_paper_ws_contract.py -q` | ❌ W0 | ⬜ pending |
| SC2 adapter | 16-01 T1, T3 | PAPER-01 | awaits calls, plain `"1h"` string, PROD `stream_url`, non-empty connections | unit | `PYTHONPATH=. uv run pytest tests/test_paper_ws_connect.py -q` | ✅ rewrite | ⬜ pending |
| SC3 fills / delay / buttons | 16-19 T1, T3; 16-35 T1; 16-04 T2 | PAPER-02 | Phase 14 lifecycle reused; measured approval delay; functional APR/SKP buttons | unit + golden | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_fill.py tests/test_paper_approval_delay_measured.py tests/test_paper_shadow_buttons.py -q` | ❌ W0 | ⬜ pending |
| SC4 criteria | 16-25 T1, T2 | PAPER-02 | evaluator constants equal D061 D (14 days, 95 percent, tolerance zero) | unit | `PYTHONPATH=. uv run pytest tests/test_paper_exit_evaluator.py -q` | ❌ W0 | ⬜ pending |
| SC5 SHADOW chain | 16-04 T1; 16-11 T3; 16-31 T1 | PAPER-02 | label `SHADOW — no real order`; APPROVE then CONFIRM, CANCEL, SKIP, expiry journaled; idempotent replay; approval expiry = TradePlan expiry (REV-12) | unit + PG | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_messages.py tests/test_paper_shadow_pg.py tests/test_paper_shadow_runtime.py -q` | ❌ W0 | ⬜ pending |
| SC6 isolation | 16-38 T1, T2, T3; 16-22 T1 | PAPER-02 | AST import graph, env refusal, behaviour spy with negative control; also covers the REV-03 test-only path | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_isolation.py tests/test_paper_runtime_env.py -q` | ❌ W0 | ⬜ pending |
| SC8 freeze | 16-09 T1, T2 | PAPER-01 | `--from-allowlist` empty gives one SKIPPED line, exit 0, never CLEAN | unit + text | `PYTHONPATH=. uv run pytest tests/test_paper_freeze_allowlist_mode.py tests/test_paper_freeze.py -q` | ❌ W0 | ⬜ pending |
| SC8 coverage (REV-01, REV-17, REV-18) | 16-15 T1, T2, T3 | PAPER-01 | only HEALTHY time covered; PLANNED_RESTART and every gap uncovered with a reason code; derived 319.2 of 336 h; missing scheduled tick is `EVIDENCE_GAP`, never CLEAN, restarts the trial with a new epoch pin | unit | `PYTHONPATH=. uv run pytest tests/test_paper_coverage.py tests/test_paper_freeze_evidence.py -q` | ❌ W0 | ⬜ pending |
| SC9 closure rule | 16-25 T3 | PAPER-01/02 | fake-adapter evidence can never yield PASS for SC1/SC2/SC7 closure | unit | `PYTHONPATH=. uv run pytest tests/test_paper_closure_rule.py -q` | ❌ W0 | ⬜ pending |
| REV-03 rehearsal | 16-39 T1, T2, T3 (owns `tests/test_paper_test_signal_rehearsal.py`; the test-only exclusion is also asserted by 16-36 T2 in `tests/test_paper_shadow_evidence_export.py` and by 16-25 T2 in `tests/test_paper_exit_evaluator.py`, rows D-18 and SC4) | PAPER-02 | test signal has its own ID, `test_only`, runs before the soak, excluded from signal/trade counts, parity, G1-G5, PAPER-03; production path does not bypass `PAPER_START_ALLOWLIST` | unit | `PYTHONPATH=. uv run pytest tests/test_paper_test_signal_rehearsal.py -q` | ❌ W0 | ⬜ pending |
| REV-15 / D-31 guard | 16-05 T1, T2, T3 | PAPER-02 (D065-WR; GOV-02 supported, not declared) | one registry of five WR items with `blocks_report` / `blocks_live_enable`; report guard uses only WR-01/06/12/13; `fixture` is machine-checkable (REV-11) | unit | `PYTHONPATH=. uv run pytest tests/test_killgate_guard.py tests/test_wr_registry_scopes.py -q` | ❌ W0 | ⬜ pending |
| REV-04/05 runner | 16-06 T1, T3; 16-12 T1, T3 | BKTS-03 (D059-5) | run refuses without an authorization whose grid hash AND dataset manifest hash match; no verdict printed; never writes the allowlist; holdout never simulated by the feasibility gate | unit | `PYTHONPATH=. uv run pytest tests/test_research_runner.py tests/test_research_feasibility.py -q` | ❌ W0 | ⬜ pending |
| D-20 parity | 16-10 T2, T3; 16-25 T2 | PAPER-01 | `decision_surface` digests identical to replay; windows 1000/300; 4h before 1h at shared closes | unit | `PYTHONPATH=. uv run pytest tests/test_paper_decision_surface.py tests/test_paper_bars.py -q` | ❌ W0 | ⬜ pending |
| Tick seam | 16-10 T1; 16-02 T2 | PAPER-01 | typed extraction leaves `run_paper_tick` bytes unchanged | unit (existing) | `PYTHONPATH=. uv run pytest tests/test_paper_start_gate.py tests/test_paper_parity.py tests/test_paper_reviewfix_pins.py tests/test_paper_feed_gates.py tests/test_paper_closed_candle.py -q` | ✅ | ⬜ pending |
| D-32 deployment | 16-32 T1, T2, T3 | PAPER-01 | soak compose renders; paper env has no `BINANCE_*`; `down -v` guard refuses the soak project | static | `PYTHONPATH=. uv run pytest tests/test_soak_compose.py tests/test_deploy_compose.py -q` | ❌ W0 | ⬜ pending |
| D-03 allowlist entry (G4-018) | 16-02 T1 | PAPER-01 | malformed entry refused at construction; allowlist literal stays `()` | unit | `PYTHONPATH=. uv run pytest tests/test_paper_allowlist_entry.py -q` | ❌ W0 | ⬜ pending |
| D-13 public adapter split | 16-03 T1, T2 | PAPER-02 | credential-free market-data adapter with no order surface (AST, negative control) | unit | `PYTHONPATH=. uv run pytest tests/test_binance_public.py -q` | ❌ W0 | ⬜ pending |
| D-05/D-06 supervisor | 16-08 T1, T3 | PAPER-01 | async start; only closed bars reach the sink tagged LIVE_WS; reconnect backfill and gaps go to sinks with reason codes | unit | `PYTHONPATH=. uv run pytest tests/test_paper_supervisor_backfill.py tests/test_paper_vocabulary.py -q` | ✅ rewrite | ⬜ pending |
| D-04 runtime state port | 16-16 T1, T3 | PAPER-01 | deterministic ids keyed on epoch and bar close; replay no-op; restore last close (per Q-J) | unit + PG | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_state.py tests/test_paper_runtime_state_pg.py -q` | ❌ W0 | ⬜ pending |
| SC1 per-bar pipeline (Q-D) | 16-24 T1, T3 | PAPER-01 | REST_WARMUP never evaluated; REST_BACKFILL per Q-D; one heartbeat record per processed bar; permutation-independent | unit | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_pipeline.py -q` | ❌ W0 | ⬜ pending |
| SC1 loop, market inputs, probe | 16-26 T1, T2, T3 | PAPER-01 | callback only enqueues; exchangeInfo constraints with ratified ttl; clock skew recorded; healthcheck tied to processed-bar age | unit | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_loop.py tests/test_paper_market_inputs.py -q` | ❌ W0 | ⬜ pending |
| SC5 CONFIRM (D041) | 16-11 T1, T2 | PAPER-02 | separate single-use confirm token bound to user id and plan hash, 60 s TTL, CANCEL and expiry journaled | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_confirm.py -q` | ❌ W0 | ⬜ pending |
| D-17 paper ledger (G4-010, REV-07 input) | 16-23 T1, T3 | PAPER-02 | simulated positions feed risk inputs; equity required, no default; exposure per Q-C; rebuild after restart | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_ledger.py -q` | ❌ W0 | ⬜ pending |
| SC3 live minutes | 16-19 T3 | PAPER-02 | REST 1m trade and mark minutes validated; poll cadence and lag required inputs | unit | `PYTHONPATH=. uv run pytest tests/test_paper_live_minutes.py -q` | ❌ W0 | ⬜ pending |
| SC5 runtime wiring | 16-31 T1, T2, T3 | PAPER-02 | alert, APPROVE, CONFIRM, simulated position in the running process; fail-closed restart; attribution | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_runtime.py -q` | ❌ W0 | ⬜ pending |
| D-18 analytics report | 16-36 T1, T2, T3 | PAPER-02 | SHADOW rows reported as system/user/opportunity; measured delay not labelled synthetic; test_only excluded; no new metric | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_evidence_export.py tests/test_analytics_lifecycle.py tests/test_analytics_approval_delay.py -q` | ❌ W0 | ⬜ pending |
| D-22 evidence export | 16-30 T1; 16-47 T1 | PAPER-01 | verifiable bundle; EVIDENCE_GAP stored in its own file; proof class from source only; publish verified | unit | `PYTHONPATH=. uv run pytest tests/test_soak_evidence_export.py -q` | ❌ W0 | ⬜ pending |
| Q-F workflow pin source | 16-47 T2 | PAPER-01 | hourly check reads the pinned epoch as decided; schedule, permissions and pins unchanged | text | `PYTHONPATH=. uv run pytest tests/test_paper_freeze_workflow_pin_source.py tests/test_deploy_workflows.py -q` | ❌ W0 | ⬜ pending |
| REV-07 / O-07 configuration | 16-34 T3 | PAPER-02 | configuration values equal the user's decision records character for character | unit | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_config_file.py -q` | ❌ W0 | ⬜ pending |
| SC7 smoke tool | 16-17 T1, T2 | PAPER-01 | evidence schema, redaction, BINANCE_ refusal, forced disconnect, archive fetch (dry-run) | unit | `PYTHONPATH=. uv run pytest tests/test_paper_ws_smoke_evidence.py -q` | ❌ W0 | ⬜ pending |
| D-27/D-29/D-30 runner report | 16-18 T3 (owns `tests/test_research_report.py` and `tests/test_modeled_costs_none_guard.py`); 16-18 T1, T2 carry their own automated checks | BKTS-03 | plateau in grid order without ranking; mark-hole count unclassified; None never read as zero cost (consumer audit); timing without tracemalloc | unit | `PYTHONPATH=. uv run pytest tests/test_research_report.py tests/test_modeled_costs_none_guard.py -q` | ❌ W0 | ⬜ pending |
| D-28 candidate validator | 16-13 T1, T2 | BKTS-03 | VALID only for a rationalized, preregistered, pinned set; exact hash printed; no write, no ranking | unit | `PYTHONPATH=. uv run pytest tests/test_research_register.py -q` | ❌ W0 | ⬜ pending |
| REV-16 identity wiring | 16-37 T3 | PAPER-01 | experiment identity carries the manifest identity in the user's route; authorization hash and identity value equal | unit | `PYTHONPATH=. uv run pytest tests/test_research_runner.py -q` | ✅ extend | ⬜ pending |
| D-33/D-34/D-35 runbook | 16-07 T1, T2, T3; 16-33 T1, T3 | PAPER-01 | D042 acceptance per condition; data-pull command; REV-08 study without a selection; soak operations section 20 | text | `PYTHONPATH=. uv run pytest tests/test_soak_runbook.py tests/test_deploy_docs.py -q` | ❌ W0 | ⬜ pending |
| SC7 unsolicited disconnect (research D3, P4) | 16-01 T3; 16-17 T2 | PAPER-01 | the forced disconnect drops the transport beneath the SDK; `adapter.last_rebuild` lists the stale stream names; a forced disconnect through any close API fails `check_forced_disconnect` | unit + live smoke | `PYTHONPATH=. uv run pytest tests/test_paper_ws_connect.py tests/test_paper_ws_smoke_evidence.py -q` | ❌ W0 | ⬜ pending |
| SC7 SDK 23 h rotation (research D2) | 16-17 T2; 16-21 T2, T3; 16-43 T3 | PAPER-01 | faked-clock reconnect at 82800 s in CI; shortened SDK timer on the real socket in the live smoke or an explicit UNPROVEN with the manual fallback; natural rotation observed in the trial soak | unit + live smoke + soak | `PYTHONPATH=. uv run pytest tests/test_paper_ws_smoke_evidence.py -q` | ❌ W0 | ⬜ pending |
| Smoke measurements (A2, A11, P20) | 16-17 T4; 16-21 T3 | PAPER-01 | SDK socket count, arrival latency, clock skew and REST 1m trade and mark lag recorded as observations, never thresholds | unit + live smoke | `PYTHONPATH=. uv run pytest tests/test_paper_ws_smoke_evidence.py -q` | ❌ W0 | ⬜ pending |
| Tick statistics and clock-skew drops (A10, P20) | 16-24 T1; 16-26 T1; 16-15 T4; 16-25 T2 | PAPER-01 | FUTURE_CLOSE drops reported by the pipeline and journaled with the tick duration in PAPER_TICK_STATS; the timing summary is report-only | unit | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_pipeline.py tests/test_paper_runtime_loop.py tests/test_paper_freeze_evidence.py -q` | ❌ W0 | ⬜ pending |
| Telegram failure handling (F3) | 16-04 T2; 16-11 T4; 16-31 T2 | PAPER-02 | 429 retry_after honoured inside the budget; failed edit after APPROVE falls back once then fails closed with CARD_DELIVERY_FAILED; "message is not modified" is success; answerCallbackQuery failure never aborts the gates; no stranded approval | unit + PG | `TRADING_CI_STRICT=1 PYTHONPATH=. uv run pytest tests/test_paper_shadow_buttons.py tests/test_paper_shadow_telegram_failures.py tests/test_paper_shadow_pg.py -q` | ❌ W0 | ⬜ pending |
| SC5 label and both time zones on every SHADOW text | 16-04 T1, T2; 16-11 T2; 16-31 T1 | PAPER-02 | the composer is the only text constructor; every message kind carries `SHADOW — no real order`, the mode, UTC and Asia/Ho_Chi_Minh stamps; the fake bot asserts it on every call | unit | `PYTHONPATH=. uv run pytest tests/test_paper_shadow_messages.py tests/test_paper_shadow_confirm.py tests/test_paper_shadow_runtime.py -q` | ❌ W0 | ⬜ pending |
| Freeze cron asserted (REV-18, G15) | 16-09 T2; 16-30 T4; 16-47 T2; 16-43 T1 | PAPER-01 | the workflow cron equals the user's Q-Q record; the slot grid follows the minute; a different schedule string is SCHEDULE_MISMATCH | unit + text | `PYTHONPATH=. uv run pytest tests/test_paper_freeze_allowlist_mode.py tests/test_paper_freeze_evidence.py tests/test_paper_freeze_workflow_pin_source.py -q` | ❌ W0 | ⬜ pending |
| Grace never CLEAN; earlier epoch auxiliary (REV-02, REV-18) | 16-15 T2, T3, T4; 16-25 T2; 16-30 T1; 16-34 T3 | PAPER-01 | one run satisfies at most one slot; a grace at or above the slot interval is refused; earlier-epoch evidence is returned untouched as auxiliary | unit | `PYTHONPATH=. uv run pytest tests/test_paper_freeze_evidence.py tests/test_paper_exit_evaluator.py tests/test_soak_evidence_export.py -q` | ❌ W0 | ⬜ pending |
| Exit-code table and refusal hold | 16-22 T1; 16-32 T1; 16-33 T1 | PAPER-01 | refusal codes 3 to 6 are disjoint from the crash status 1 and from 7; `--hold-on-refusal` keeps a refused container up; the compose command passes it | unit + static | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_compose.py tests/test_soak_compose.py tests/test_soak_runbook.py -q` | ❌ W0 | ⬜ pending |
| No late signal independent of Q-D (D-06, L-11) | 16-29 T1 | PAPER-01 | no bar closed during downtime reaches `evaluate_closed_bar` under any of the three evaluation rules, with a negative control | unit | `PYTHONPATH=. uv run pytest tests/test_paper_runtime_restart.py -q` | ❌ W0 | ⬜ pending |
| External heartbeat sender (D042 condition 1; healthchecks.io, user choice 2026-10-09) | 16-50 T1, T2, T4 | PAPER-01 | success ping only while the collector probe passes; fail ping only with `--fail-ping`; the only docker subcommand is `exec` (static check with negative control); the URL never appears in output, argv, units, logs or acceptance.json (a sentinel is asserted absent in every test; the validator exits 2 on a ping-URL-shaped value); `--install-timer` refuses to run without `--interval-seconds`; no catch-up in the timer | unit (stub docker, stub curl, loopback-only real curl) | `TRADING_CI_STRICT=1 PYTHONPATH=. uv run pytest tests/test_deploy_heartbeat.py tests/test_soak_runbook.py -q` | ❌ W0 | ⬜ pending |
| Heartbeat documentation, source register and guide (D-34, L-07, O-12) | 16-50 T3, T4 | PAPER-01 | RUNBOOK 11.4, 11.9, 13.5, 17, 19.3 and 19.4 describe the sender and name no interval or grace number; SOURCES rows carry URL, date and the not-verified-live label; the O-12 record names the service and leaves interval and grace open; the guide has a card for every new deploy file | text | `PYTHONPATH=. uv run pytest tests/test_deploy_docs.py tests/test_soak_runbook.py tests/test_deploy_guide_vi.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] All new test files in the map above
- [ ] SDK-shaped fake client and handle builders (reuse SDK model classes for events) — 16-01 T1
- [ ] Real-shaped kline fixtures (close = open + interval - 1 ms) — 16-08 T2
- [ ] Rewrite `tests/test_paper_ws_connect.py` and `tests/test_paper_supervisor_backfill.py` (they pin the fictional handle API) — 16-01 T1, 16-08 T1
- [ ] Disposable PostgreSQL for `*_pg.py` tests on the execution machine — preconditions of 16-11 T3, 16-16 T3, 16-29 T3
- [ ] New modules scanned by `tests/test_domain_no_float.py` — 16-05 T1 (killgate_guard) and 16-10 T3 (glob over `src/paper` and `src/research`)
- [ ] Protocol v2.2.0 amendment (D065 item 2) is a separate prerequisite task, not a Phase 16 code plan; plan 16-28 T3 gates the closure chain on it and records its alignment tests

---

## Manual-Only Verifications

| Behavior | Requirement | Plan/Task | Why Manual | Test Instructions |
|----------|-------------|-----------|------------|-------------------|
| Live WS smoke: `ws_subscribe` succeeds and delivers closed candles | PAPER-01 (SC7) | 16-21 T2, T3 | needs real Binance WS | run the smoke on the connected machine; evidence file with SDK versions, per-interval closed-event counts, recovery from a forced UNSOLICITED disconnect (with the stale stream entries proving the path), the SDK reconnect on the real socket or an explicit UNPROVEN with the manual fallback, SDK socket count, arrival latency, clock skew and REST 1m lag as observations |
| Real Telegram APPROVE then CONFIRM tap log | PAPER-02 (SC5) | 16-40 T3 | needs real Telegram | tap log with timestamps from the rehearsal window |
| Host start gate (`SKIPPED (allowlist empty)`) | PAPER-01 (SC1) | 16-40 T2 | only a real host | evidence file with commit, image id, log excerpt, exit code |
| EC2 acceptance per D042 condition (encrypted EBS, chrony, Elastic IP, budget alert, Object Lock, restore drill) | PAPER-01 | 16-20 T2, T3; 16-49 T3; 16-43 T2 | only a real host | acceptance table; check `get-ebs-encryption-by-default` in ap-southeast-1 (state of a new account is not documented) |
| Trial soak exports and freeze ticks | PAPER-01 (SC8) | 16-43 T2, T3; 16-44 T1 | wall-clock | 14 calendar days, 95 percent HEALTHY coverage, every scheduled tick CLEAN |
| Real healthchecks.io ping, alert and recovery for a stopped collector; systemd credential delivery to the `trading` user; timer firing | PAPER-01 (D042 condition 1) | 16-50 operator verification (not an executor step) | needs the EC2 host with the collector on it and the real monitor | set the URL with `--set-url`, install the timer with the user's interval, stop the collector longer than the check's period plus grace, confirm the alert and the recovery notice, record the UTC times in `evidence/16-50-operator-verification.md` (never the URL) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency measured and recorded
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
