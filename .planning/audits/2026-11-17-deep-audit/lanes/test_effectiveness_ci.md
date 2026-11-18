# Lane X03: test_effectiveness_ci

## Scope
`tests/**` (sampled), `tests/support/*`, `tests/conftest.py`, `.github/workflows/*`, `AUDIT\tool-output\*`.
Focus (coordinator): (1) skip/xfail classification and CI coverage; (2) fake exchange vs real Binance;
(3) tests weakened in history since 2026-10-01; (4) AST/structural guard coverage gaps.
Builds on `lanes/mutation_probe.md` (G-1901..1903) and `lanes/evidence_reproducibility.md` (G-1508).

## Coverage
| file | level | note |
|---|---|---|
| `tool-output/pytest.txt` | DEEP_READ | every SKIPPED line aggregated (`tmp/test_effectiveness_ci/skips.txt`) |
| `tool-output/ruff-check.txt`, `ruff-format.txt`, `mypy-src.txt`, `decision-alignment.txt` | METADATA_ONLY | clean per coordinator (TODO.md:71) |
| `.github/workflows/ci.yml` | DEEP_READ | trigger, PG service, strict mode, timeouts |
| `.github/workflows/registry-gate.yml`, `research-gate.yml`, `paper_freeze_check.yml` | NORMAL_READ | triggers and pytest selections |
| `tests/infra_helpers.py`, `tests/pg_support.py` | NORMAL_READ | strict skip -> fail, disposable DB names |
| `tests/test_demo_twin_s07_restart_cuts.py`, `test_demo_twin_s11_db_outage.py`, `test_demo_twin_s12_daily_stop.py` | NORMAL_READ | the 3 strict xfails |
| `tests/test_phase25_gate.py` | METADATA_ONLY | xfail-register check (lines 1194-1221) |

| `tests/support/fake_binance_exchange.py` | DEEP_READ | whole file, compared with `lanes/exchange_facts.md` and DVM rows |
| `tests/support/ast_guards.py` | DEEP_READ | guard helpers, applied to all of `src` by probe |
| `tests/test_domain_no_float.py`, `test_core_tracer.py`, `test_backtest_purity.py`, `test_analytics_purity.py`, `test_live_ast_guards.py` | NORMAL_READ | guard scope |
| `tests/test_demo_twin_s08_stream_loss.py` | NORMAL_READ | xfail removal history |
| `tests/test_demo_rehearsal_flow.py`, `test_demo_rehearsal_safety.py` | METADATA_ONLY | commit `d78721c7` diff of test names |
| `git log -p --since=2026-10-01 -- tests/` (1,186 commits) | NORMAL_READ | scripted scan for skip/xfail, tolerances, removed asserts; top commits read |
| other `tests/support/*` (account_fakes, protection_doubles, reconcile_doubles, live_*_rig, intent_store_fakes, ...) | METADATA_ONLY | listed; intent-store fake status check is covered by G-1901 |
| remaining `tests/**` (about 900 files) | NOT_READ | sampled only through the scans above |

## Verified Safe Areas
- **The emergency close does not trust the fake's synchronous FILLED answer.** `src/execution/emergency_close.py:748-758` marks an answer only as `seen` and polls by id, so the fake's default RESULT-like FILLED reply (real default is ACK, F39) cannot hide an ACK-handling bug.
- **No widened tolerance and no silent skip were added to tests since 2026-10-01** (scan of 1,186 commits); new tolerances are zero or exact; the one xfail removed (S08) was replaced by a stricter assertion (`tests/test_demo_twin_s08_stream_loss.py:176-194`).
- **Simulator goldens are regenerated only with a semantics version bump and a DECISIONS row** (commits `ffda8c4c`, `c96fa0d9`, `6f599ddd`; D073-D076).
- **`src/live`, `src/backtest`, `src/analytics` purity guards discover modules by glob**, so modules added later are covered from their first commit (`tests/test_live_ast_guards.py:3`, `tests/test_backtest_purity.py:3`).
- **Static tools**: ruff check, ruff format, mypy src (291 files) and decision alignment all exit 0 (TODO.md:71); pytest `-n 4` exit 0 with 0 failures.
- **PostgreSQL skips cannot silently vanish in CI.** `tests/pg_support.py:50-54` calls `infra_skip`, which FAILS under `TRADING_CI_STRICT=1` (`tests/infra_helpers.py:43-61`); `ci.yml:24` sets `TRADING_CI_STRICT: "1"` and `ci.yml:31-45,72` provides a digest-pinned postgres:17.11 service plus `TEST_DATABASE_URL`. So on a CI run every `*_pg` test executes or the run fails. The same strict mode turns the 14 shellcheck skips and the platform skips (Linux runner has POSIX modes and symlinks) into executed tests in CI.
- **The 3 xfails are strict and registered.** All three are `strict=True` (an accidental fix turns red) and `tests/test_phase25_gate.py:1197-1221` fails if a twin xfail is not named in `25-DEFERRED.md` or if fewer than 3 exist. Each is a KNOWN safety gap, correctly described in `.planning/phases/25-demo-integration-test-campaign/25-DEFERRED.md:60,66,70` (see table below) and already analysed by lanes failure_scenarios / live_risk_state / exec_*; not re-reported here.
- **Demo scenario skips are by design** (owner-only, `-m demo` + `TRADING_DEMO_RUN=1`, AGENTS.md); each has a `tests/test_demo_twin_s*.py` twin that does run.

## Decision review
| decision/doc rule governing this area | verdict | yardstick | reason |
|---|---|---|---|
| `TRADING_CI_STRICT=1`: missing infrastructure fails instead of skipping (13.1, `tests/infra_helpers.py:43-61`) | SOUND | testing practice | prevents the classic silent-skip CI; the PG service makes the 872 local skips real tests in CI |
| Strict xfail twins for known Demo-scenario defects, each registered (`tests/test_phase25_gate.py:1197-1221`) | SOUND | testing practice | keeps known safety gaps visible and turns red when fixed by accident |
| Demo scenarios owner-only, never in CI (AGENTS.md) | SOUND | owner goals (no agent touches an exchange account) | each has an offline twin |
| D-25/F-603 Binance-semantics fake with provenance labels and opt-in Demo rules | DOUBTFUL | exchange behaviour (DVM-19, positionRisk lag) | the labelling is good, but the default is a zero-lag exchange, the opposite of what Demo showed; see G-1400 |
| CI runs only on push/PR to `master`, 30-minute test job (13.1 D-01..D-03) | DOUBTFUL | arithmetic (suite x1.76 since the 24-min measurement) and project workflow (weeks of work on `develop`) | see G-1401 |
| AGENTS.md "Invariants that are machine-enforced" (core purity, no wall clock, no float) | DOUBTFUL (as stated) | code of the guards | true for backtest/analytics/live, only partly for core/risk; see G-1402 |
| AGENTS.md "`*_pg.py` suffix (26 files) needs PostgreSQL" | WRONG (stale number) | file count | 41 `*_pg.py` files plus 9 other files with PG cases; harmless because every PG case skips through `infra_skip` |

## Analysis notes
### Working notes: skip and xfail classification (part 1, written 2026-11-18)
Audit run (`pytest -m "not docker" -n 4`, TEST_DATABASE_URL unset on purpose) skip reasons, aggregated from the `SKIPPED [n]` lines:

| reason | count | files | never exercised locally | CI (`ci.yml` test job) |
|---|---|---|---|---|
| `TEST_DATABASE_URL is not set` (+1 `live-PG analytics store`) | 872 | 41 `*_pg.py` files plus 9 non-suffixed files with PG cases: `test_controller_rehydrate.py`(7), `test_intent_result_contract.py`(24), `test_live_approval_sender.py`(4), `test_live_safe_mode_drill.py`(1), `test_paper_replay_inputs.py`(1), `test_paper_test_signal_rehearsal.py`(1), `test_persistence_engine_timeouts.py`(2), `test_soak_evidence_export.py`(1), `test_analytics_store.py`(1) | everything that depends on real DB semantics: exactly-once placement / write-ahead (`test_execution_exactly_once_pg` 18, `test_execution_write_ahead_pg` 8), intent recovery after restart (`test_intent_recovery_pg` 16, `test_live_replay_restart_pg` 10), approval replay / callback redelivery / consume-approved-quantity (5+12+19), risk reservations incl. margin and approval (90+20+24), day-risk latch (22), SAFE_MODE persistence (5), journal append-only triggers and transitions (60+59), migrations (70), constraints (48+16) | runs, with PG 17.11 service; strict mode fails the job if PG is missing |
| shellcheck not on PATH | 14 | `tests/infra_helpers.py:50` | `deploy/*.sh` lint tests | runs (ubuntu-24.04 image ships shellcheck; strict) |
| file modes / NTFS POSIX modes | 5 | `test_deploy_heartbeat.py`(4), `test_bootstrap.py`(1) | heartbeat/bootstrap secret-file mode checks | runs on Linux |
| symlinks unavailable | 2 | `test_analytics_files.py`, `test_user_data_smoke_dry_run.py` | symlink refusal paths | runs on Linux |
| demo scenario owner-only | 22 | `tests/demo/test_demo_s00..s19` (s07 has 3) | real Demo behaviour | never (by design); twins run |

Note: AGENTS.md "Tests" says the `*_pg.py` suffix is "26 files"; the snapshot has 41 `*_pg.py` files and 9 more files with PG-only cases (DRIFT of the doc only; harmless because the skip goes through `infra_skip`).

The 3 xfails (all `strict=True`):
| test | pinned defect | safety? | register |
|---|---|---|---|
| `tests/test_demo_twin_s07_restart_cuts.py:444` `test_cut_b_a_late_restart_close_lets_the_operator_leave_safe_mode` | after a late restart + deadline close, STOP_LOSS intent stays UNKNOWN, `/safemode_exit` refuses | yes: operator cannot leave SAFE_MODE (fail-closed direction, availability) | 25-DEFERRED.md:60 (25-12-F1) owner-open |
| `tests/test_demo_twin_s11_db_outage.py:182` `test_after_the_database_returns_and_the_exit_a_new_request_is_placed` | PROTECTION_TRANSITION rows not spilled during DB outage; reservation stays RESERVED; CLUSTER_CAP_REJECT | yes, fail-closed direction (blocks entries) | 25-DEFERRED.md:66 (25-14-F1) |
| `tests/test_demo_twin_s12_daily_stop.py:158` `test_a_resting_entry_is_cancelled_at_daily_stop_and_the_alert_is_journaled` | `enforce_daily_state` has no production caller (confirmed: only `src/execution/daily_stop.py` defines it, `src/ops/alerts.py` mentions it in text) -> resting entry survives DAILY_STOP, no alert | yes, fail-OPEN direction (an entry can still fill after the daily stop) | 25-DEFERRED.md:70 (25-15-F1) |
So yes: all three are known safety defects pinned as "expected to fail". They are honest pins (strict, registered), not hidden weakening. The fail-open one (25-15-F1) is covered by lanes live_risk_state / failure_scenarios.

### Working notes: fake exchange vs Binance (part 2)
`tests/support/fake_binance_exchange.py` (`BinanceSemanticsFakeAdapter`, used by 30 test files) compared with `lanes/exchange_facts.md` and `docs/operations/DEMO_VS_MAINNET.md`:

| behaviour | fake | real Binance (doc / Demo) | effect on tests |
|---|---|---|---|
| read-after-write of an order/algo by id | found at once (`query_*_by_client`, :565-614) | DVM-19: algo by-id query answers -2013 for ~90 s while the order is NEW | no test sees a false "not found" of a resting order unless it scripts one -> G-0250 (exec_gapfill) |
| position after a fill | `fill()` moves `self.positions` synchronously (:265-317); `snapshot_positions` reads it (:793-820) | positionRisk lags the fill (project's own comment `src/execution/protection.py:1794-1796`) | two lagging zero reads never occur -> G-0300 (exec_protection), G-0253 (exec_gapfill) |
| algo state after cancel | opt-in `algo_cancel_query_lag` (default 0, used by 3 files) | Demo: NEW for ~1 s after cancel (plan 24-21) | modeled only where opted in |
| entry placement validation | accepts any price/qty/GTD (:471-511) | PRICE_FILTER/LOT_SIZE/-4164/-5040 GTD >= now+600 s/PERCENT_PRICE | tests of the placement chain cannot catch a mis-quantized or too-short GTD order; production guards upstream (quantization, `min_remaining_validity_seconds = 900`) are tested on their own |
| stop placement with trigger already crossed | accepted (:513-562) unless scripted `reject_next_algo(-2021)` | -2021 "Order would immediately trigger" (F33) | covered by scripting: 29 test files mention -2021 |
| stop trigger | `trigger_stop` called by the test, fills exactly at trigger price, always FINISHED (:415-436) | STOP_MARKET fills at market (slippage); after migration "no margin check before trigger", may end REJECTED/EXPIRED (F30) | loss-size tests through the fake see zero slippage; a stop that vanishes is exercised by cancel/EXPIRED edits (`test_demo_twin_s16_manual_close.py:131`) |
| MARKET close answer | FILLED + executed qty by default; ACK only with `market_close_ack_only` (2 uses) | default `newOrderRespType` ACK (F39) | harmless: `src/execution/emergency_close.py:748-758` ignores the answer's status and polls by id |
| cancel of an unknown/filled order | returns None silently (:830-848) | -2011 / -2013 (F11) | the ORDER_ABSENT branch is exercised only by scripted errors (13 files mention -2011) |
| GTD expiry | never happens; tests edit `history[...].status = "EXPIRED"` (`test_protection_coordinator.py:403-408`) | may be delayed (F38) | covered by edits |
| 5xx / timeouts / -1007 | only scripted (`fail_next`); a scripted failure leaves state untouched unless the test changes it (:383-392) | 503 "Unknown error" may have executed (F07) | ambiguous-but-executed is opt-in per test -> G-0252 (exec_gapfill) |
| partial fills | scripted `fill(quantity=...)` | normal on mainnet, rare on Demo | covered when scripted |
| position mode | ONE_WAY, one signed Decimal per symbol | hedge mode exists | intended (system refuses hedge) |
| liquidation price in position rows | `None` (:810) | always present | liquidation watch treats `None` per `src/execution/liquidation_watch.py:108-133`; exchange-value branch exercised only by other doubles |

### Working notes: test history since 2026-10-01 (part 3)
`git log -p --since=2026-10-01 -- tests/` = 1,186 commits, 16.9 MB patch (`tmp/test_effectiveness_ci/tests_log.patch`). Scan: +32,256 assert lines, -1,474 assert lines.
- **Added skip/xfail (38 lines):** all classified. (a) infra skips through `infra_skip` (strict in CI); (b) "planning dir / REQUIREMENTS.md not in this checkout" skips in phase gate tests (only on filtered PR branches; CI checks out the full tree with `fetch-depth: 0`); (c) platform skips (symlinks, POSIX modes); (d) demo owner-only skip hook (`6943e07b`); (e) 4 strict xfails of Phase 25 twins. The S08 xfail (`69f808cf`, "CONFIRM after a drop is still placed") was removed one commit later (`5119ecc8`, tests-only) and replaced by a STRONGER test asserting `place_entry_calls == 0` and refusal `UNCERTAIN_ACCOUNT_STATE` (`tests/test_demo_twin_s08_stream_loss.py:176-194`): the RED stub was wrong, not the code; this is a tightening. The skip `"the owner has filled the shipped limits file"` (`aeb61e79`) was removed again in `2043f0b8`.
- **Tolerances:** no widened numeric tolerance found. New tolerances are zero or exact (`Fraction(1, 1_000_000)` for the liquidation oracle, "parity (tolerance zero)", `_TOLERANCE_SECONDS = 2` on Demo-scenario wall waits only).
- **Removed asserts, largest commits:** `d78721c7` (-226, `test_demo_rehearsal_flow.py` 37 tests deleted) follows the rewrite of `scripts/demo_rehearsal.py` onto the composed live process (`5cf8e00b`); the deleted tests exercised the old hand-stepped rehearsal path that no longer exists (e.g. its own constraint recheck step). Not a weakening of `src` coverage, but the composed smoke's own guard tests (`test_demo_rehearsal_safety.py`, +7 tests) are far fewer. `fbcda93f`/`8cd4a5e4`/`0f6da371` (-91/-43/-24) are RED rewrites of Phase 19 (fill-driven model replaced entry-time stop); `00601566` is a reformat.
- **Goldens regenerated with a behaviour change:** 31 commits since 2026-10-01 change `tests/fixtures/**` and `src/**` together. Spot-checked: `6f599ddd`, `c96fa0d9`, `ffda8c4c` (simulator semantics 2.1.0-2.3.0 with protocol/DECISIONS bumps D073-D076: governed); `466ea5f8` deletes the phase9 attach goldens with the rewrite of attach (replacement named in `tests/test_execution_attach.py:26`); `36c420d9` edits the orphan-divergence input so it no longer carries a resting entry, together with a new exemption in `src/reconcile/compare.py` (commit body: "No assertion removed or loosened"; the exemption narrows what is an orphan, a reconcile-lane question, see Open Questions); `d1c971c7` regenerates one alert text golden. No golden was found regenerated to hide a money-value change.

### Working notes: AST guards and structural tests (part 4)
Probes: `tmp/test_effectiveness_ci/probe_guard_scope.py` (`.out`), `probe_core_guard.py` (`.out`).
- No-float (`tests/test_domain_no_float.py`): 118 modules (explicit list + globs `src/backtest/*.py`, `src/paper/*.py`, `src/research/*.py`). Decimal-path modules not in it: `src/risk/cost_guards.py`, `src/risk/live_commission.py`, `src/core/_decimal.py` (no other float guard names them), plus `src/risk/cost_rates.py`, `src/domain/{exchange_errors,lot_filters,transitions,algo_status,stream_records}.py` (each covered by a phase-gate float check). All are float-free today.
- Wall clock: `src/live` is glob-guarded (`tests/test_live_ast_guards.py:3`, allow-list), `src/backtest` and `src/analytics` glob-guarded (`test_backtest_purity.py`, `test_analytics_purity.py`). Execution/reconcile modules are guarded by per-phase lists (25/35 and 9/9 named). `src/core` (7 modules) and `src/research` have NO wall-clock guard; `src/risk` has per-module lists for 6/16. Today no pure module reads a clock; uncovered clock reads are CLI/ops edges plus defaults `src/approval/mapping.py:119-120` and `src/paper/supervisor.py:199` (injectable fallbacks).
- `src/core` purity: only `tests/test_core_tracer.py:378-410`, a fixed list of 5 files (`pivots.py`, `_decimal.py` not included) and forbidden roots `{polars,pandas,numpy,binance,sqlalchemy,pydantic}`; root matching means `binance_sdk_derivatives_trading_usds_futures`, `binance_common`, `httpx`, `websockets`, `telegram`, `psycopg`, `duckdb`, `socket`, `src.adapters`, `src.db` all pass (probe). -> G-1402.
- SDK confinement: no repo-wide "SDK imported only under src/adapters" guard; today `src/live/exchange.py` and `src/live/stream.py` import `binance_common.configuration` (composition root; see Open Questions).

## Findings
### G-1400
- Severity: MEDIUM (now) / HIGH (mainnet with placement enabled)
- Confidence: CONFIRMED
- Classification: GAP
- Category: test double more orderly than the exchange
- Component: `tests/support/fake_binance_exchange.py` (`BinanceSemanticsFakeAdapter`, used by 30 test files)
- File: tests/support/fake_binance_exchange.py
- Lines: 265-317, 565-614, 793-819
- Rule: charter §4 items 1-3; DVM-19 (`docs/operations/DEMO_VS_MAINNET.md:58`); the project's own comment `src/execution/protection.py:1794-1796` "positionRisk lags the fill"
- Known-prior: the fake's header labels its rules ([DEMO]/[DOC]/[ASSUMED]); the zero read lag is not among them. Escaped defects of this class found by this audit: G-0250, G-0253 (exec_gapfill), G-0300 (exec_protection).
- Evidence: `fill()` moves `self.positions` in the same call (`:305 self._apply_position_delta(record.symbol, signed, fill_price)`) and `snapshot_positions` returns `self.positions` (`:793-819`); `query_order_by_client` / `query_algo_order_by_client` answer `found=True` for any order in `open_orders` / `open_algos` immediately after `place_*` (`:569`, `:593`). The only lag the fake can model is the post-cancel algo status (`algo_cancel_query_lag`, default `timedelta(0)`, `:201`, `:207`; opted in by 3 test files). Demo answered -2013 for a just-placed NEW algo for about 90 s (DVM-19), and the position read lags the fill. A failure is scriptable only through `fail_next` / `reject_next`, which never change state (`:383-392`).
- Expected: the protection, reconcile and emergency-close rigs run by default (or in a parametrised second pass) with a read lag on by-id queries after placement and on position reads after a fill, so a step that treats one lagging read as truth fails a test.
- Actual: every lag-class behaviour is tested only where an author thought of it and scripted it; three such defects were found by other lanes, each with "the fake has no read lag" as the reason the tests miss it.
- Reproduction: read the cited lines; `tmp/exec_protection/probe_lag.py` shows the coordinator once a lag is injected.
- Impact: green tests for code that, against the real exchange, closes a protected position or holds SAFE_MODE on a transient "not found" or zero read, or treats a lagging zero as flat. Now: Demo campaign noise and false SAFE_MODE. Mainnet: unnecessary market closes (fees, slippage) or a wrong FLAT transition on a live position.
- Why tests miss it: this is the reason; the fake is consistent by construction.
- Remediation: add a read-lag mode to the fake (by-id not-found window after placement; position snapshot delayed N reads after a fill; optionally a stale open-order list) and run the protection, reconcile and emergency-close suites once with it on. Label the zero-lag default `[ASSUMED]` in the header like the other rules.

### G-1401
- Severity: MEDIUM (now) / MEDIUM (mainnet)
- Confidence: SUSPICIOUS
- Classification: GAP
- Category: CI capacity; the only place the PostgreSQL tests run
- Component: `.github/workflows/ci.yml` job `test`
- File: .github/workflows/ci.yml
- Lines: 8-12, 30, 72-73
- Rule: AGENTS.md "Tests" (the sequential suite is the CI form); G-1508 (no recorded PG gate since 2026-10-20)
- Known-prior: none found (no CI run result is recorded in `.planning/`).
- Evidence: `timeout-minutes: 30` (set 2026-10-01 in `c151d5a2`, never changed) for `uv run pytest -m "not docker" -rs -p no:cacheprovider`, sequential, with PostgreSQL. The project's own measurement (`.planning/quick/261020-xd4-*/xdist-measurements.txt`): sequential about 24 min for 10,412 tests on a 16-thread dev machine. The selection is now about 18,300 tests (audit run 17,380 passed + 915 skipped + 3 xfailed, TODO.md:72), x1.76; linear scaling gives about 42 min on the same machine, before a smaller hosted runner. `pytest-timeout` is not installed (G-1903), so one hanging test consumes the whole budget. CI triggers only on push/PR to `master` (`ci.yml:8-12`; registry-gate and research-gate the same); master's first-parent history has merges on 2026-10-25 and then 2026-11-15 (PR #3) carrying Phases 20-25 at once.
- Expected: CI evidence that the full sequential suite, including every `*_pg` test, completed on the commit the Demo runs used.
- Actual: no CI result is recorded anywhere; the arithmetic says the job most likely exceeds 30 min and is cancelled. If so, the PostgreSQL tests (exactly-once placement, approval consume, reservations, SAFE_MODE persistence, intent recovery; G-1901 shows the approval-status gate is pinned only there) ran nowhere since 2026-10-20.
- Reproduction: owner: open the Actions run of PR #3 / the master push of 2026-11-15 and read the `test` job's duration and conclusion. Or time `uv run pytest -m "not docker"` sequentially with TEST_DATABASE_URL.
- Impact: if confirmed, the green status relied on by the phase gates is not backed by any run of the database-semantics tests.
- Why tests miss it: process; `tests/test_deploy_workflows.py:87` only checks that some `timeout-minutes` exists.
- Remediation: record the CI run (id, duration, conclusion) with each merge; raise the timeout or use `-n` in CI (the xdist runs give identical pass/skip counts per the measurement file); add `pytest-timeout` with a per-test cap; run CI on `develop` pushes too.

### G-1402
- Severity: LOW (now) / LOW (mainnet)
- Confidence: CONFIRMED
- Classification: GAP
- Category: structural guard scope
- Component: `src/core` purity guard; wall-clock and no-float guard lists
- File: tests/test_core_tracer.py
- Lines: 378-410
- Rule: AGENTS.md "Invariants that are machine-enforced": "`src/core` stays pure - no Polars/pandas/NumPy/Pydantic/SDK/network imports"; "No wall clock in pure modules"; "Decimal-only ... no float(...)"
- Known-prior: none
- Evidence: the only `src/core` import guard iterates `for fname in ("__init__.py", "types.py", "features.py", "strategy.py", "planner.py")` with `forbidden = {"polars", "pandas", "numpy", "binance", "sqlalchemy", "pydantic"}` and compares `alias.name.split(".")[0]`. Probe `tmp/test_effectiveness_ci/probe_core_guard.out`: `import binance_sdk_derivatives_trading_usds_futures`, `from binance_common...`, `import httpx`, `websockets`, `telegram`, `psycopg`, `duckdb`, `socket`, `from src.adapters...`, `from src.db...` are all `caught=False`; `src/core/pivots.py` (used by planner and strategy) and `src/core/_decimal.py` are not in the list. No test applies a wall-clock check to any `src/core` module (probe `probe_guard_scope.out`: core 0/7, research 0/11). `src/risk/cost_guards.py` and `src/risk/live_commission.py` are in no float guard. By contrast `src/backtest`, `src/analytics` and `src/live` use glob-discovered guards with a complete forbidden set (`tests/test_backtest_purity.py:3-7`, `tests/test_live_ast_guards.py:3`).
- Expected: the "machine-enforced" invariants hold for every module of the package, including modules added later, as the backtest/analytics/live guards do.
- Actual: all these modules are clean today (probe), so nothing is broken; a future SDK, network or clock import into `src/core/pivots.py` or a new core module would pass CI.
- Reproduction: `python -B tmp/test_effectiveness_ci/probe_core_guard.py snapshot`.
- Impact: the deterministic no-AI core loses its only automatic fence for part of the package; drift would be caught by review only.
- Why tests miss it: the guard predates `pivots.py` and was written as a fixed list.
- Remediation: run `tests/test_analytics_purity.find_violations` over `src/core/*.py` and `src/risk/*.py` by glob (it covers clocks, float shapes and forbidden imports) and add the SDK/network roots to the forbidden set.

## Owner decisions
- **How CI must prove the database tests ran.** Example: the PR #3 merge of 2026-11-15 carried Phases 20-25 (about 18,300 tests, 872 of them PostgreSQL). Options: (a) keep the 30-minute sequential job and record each run's duration and result; (b) run CI with `-n 4` (the project measured identical pass/skip counts) and keep the sequential run only for the recorded gate; (c) (b) plus CI on every `develop` push. Each costs runner minutes; (a) may simply time out (G-1401).
- **Whether the fake exchange should lag by default.** Making lag the default will turn some existing green tests red (they assume instant consistency); keeping it opt-in keeps finding lag bugs by chance (G-1400).

## Open Questions
- CI results are not readable from this audit (only official exchange docs may be fetched). Did the `test` job of the 2026-11-15 master push finish, and in how many minutes? (G-1401)
- Reconcile lane: `36c420d9` exempts a protective whose plan's entry is open from ORPHAN_PROTECTIVE (`src/reconcile/compare.py`) and edited the orphan fixture so the old test still yields an orphan. Is there a test that a protective with an open entry but a wrong side or wrong quantity is still flagged?
- Adapter lane: `src/live/exchange.py` and `src/live/stream.py` import `binance_common.configuration`; there is no repo-wide guard that SDK modules are imported only under `src/adapters` (AGENTS.md "SDK types never leave"). Intended for the composition root?
- `tests/test_demo_rehearsal_flow.py` lost 37 tests in `d78721c7` when the rehearsal moved onto the composed process; whether every safety behaviour of the old script (e.g. the zone cushion refusal, a wrong-action press) is pinned by a `src`-level test was spot-checked only (9 test files mention wrong-action presses; the constraint snapshot store is pinned by `tests/test_constraint_snapshot.py` and `tests/test_constraint_snapshot_pg.py`; a test of a filter drift refusal between plan and placement in `src` was not traced).
- The fake's stop trigger fills exactly at the trigger price (`tests/support/fake_binance_exchange.py:415-436`); any daily-loss or realized-risk test that drives losses through `trigger_stop` sees zero slippage. Lane live_risk_state may want to check whether a slippage case exists.
## DONE
