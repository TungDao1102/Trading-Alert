# Lane L1: requirements_docs_plan

Findings are F-101..F-1xx. Snapshot 63ca176, read-only. The lane checks traceability and consistency: docs ↔ docs, REQUIREMENTS ↔ ROADMAP ↔ PLAN ↔ SUMMARY ↔ code ↔ tests. It does not redo the doc-soundness findings F-001..F-058 (stage A); where a finding touches them it cross-references instead. Planning-decision soundness belongs to B1/B2.

Method:
- Direct reading plus `codegraph explore`.
- Two read-only helper passes that spot-checked SUMMARY claims, 3+ per phase for 02–06 and 07–10. The lane re-checked every helper claim it promoted to a finding.
- Small probes in `tmp/requirements_docs_plan/`:
  - `registry_gate_probe.py` re-runs the registry-gate CI logic.
  - `enum_probe.py` diffs the code enums against the GLOSSARY.

## Scope

- **Docs:** 00_PRODUCT_SCOPE, DECISIONS, DOC_STATUS, GLOSSARY, TECHNOLOGY_STACK, data/DATA_MODEL, configuration/CONFIGURATION, trading/RISK_MANAGEMENT, trading/EXECUTION_SPEC, trading/SIGNAL_AND_ALERTS, backtest/BACKTEST_SPEC, testing/TESTING_STRATEGY (outline plus §§8–11), integration/TELEGRAM, operations/SECURITY_AND_OPERATIONS, operations/RUNBOOK (outline), implementation/IMPLEMENTATION_PLAN, research/RESEARCH_PROTOCOL (outline plus §§1, 3, 4), and the families' trend-pullback/breakout-retest sheets (baselines, parameters, status). Also AGENTS.md.
- **Planning:** PROJECT, REQUIREMENTS, ROADMAP, STATE (head), v0.3-MILESTONE-AUDIT, and all phase CONTEXT "discretion" sections. Also: all SUMMARY frontmatter `requirements-completed`; the VERIFICATION headers for 01–06 and 07.1; 05-VERIFICATION SC1/RISK-01; 02-VERIFICATION human items; 02-05-SUMMARY off-host section; 01-04-SUMMARY and negative-test evidence; 06-REVIEW-FIX WR-02; 04-REVIEW-FIX CR-03/CR-05; 09-REVIEW-DISPOSITION; 09-REVIEW-FIX WR-07; 09 deferred-items.
- **CI/infra:** .github/workflows/{research-gate, registry-gate, paper_freeze_check}.yml, pyproject.toml, Dockerfile, docker-compose.yml, .env.example, params/**/*.toml (list plus baseline-v3), and tests/fixtures/phase4/parameters.json.
- **Code, targeted reads for traceability:**
  - `src/domain/enums.py`, `ids.py`, `signal.py`
  - `src/db/models.py` (tables)
  - `src/execution/enablement.py`, `placement.py`, `manager.py` (signatures and TP legs)
  - `src/backtest/simulator.py` (run loop, entry/exit), `experiment.py`, `report.py` (slices)
  - `src/core/planner.py` (geometry)
  - `src/risk/sizing.py`, `portfolio.py` (daily-state)
  - `src/ops/backup.py`, `health.py` (function list)
  - `src/adapters/binance_usdm.py` (method list), `telegram_notify.py` (function list)
  - `src/reconcile/safe_mode.py` (function list)
  - entry points (`__main__` grep)
- **Tool output:** tool-output/{ruff-check, ruff-format, mypy-src, pytest}.txt, tail only.

## Coverage

| File | Level | Note |
|---|---|---|
| .planning/REQUIREMENTS.md | DEEP_READ | 30 REQ-IDs, checkboxes, traceability |
| .planning/ROADMAP.md | DEEP_READ | phases 1–17, SC, plan lists, progress table |
| .planning/PROJECT.md | DEEP_READ | stale since init |
| .planning/STATE.md | NORMAL_READ | frontmatter/head |
| .planning/v0.3-MILESTONE-AUDIT.md | DEEP_READ | known M1–M4, 12 orphaned |
| .planning/phases/*/??-CONTEXT.md | NORMAL_READ | discretion/deferred sections only |
| .planning/phases/*/*-SUMMARY.md | NORMAL_READ | frontmatter for all; bodies spot-checked via helpers (02–10) |
| .planning/phases/0[1-6]*/*-VERIFICATION.md, 07.1-VERIFICATION.md | NORMAL_READ | status/score/human items; 05 SC1 deep |
| .planning/phases/02-data-foundation/02-05-SUMMARY.md | NORMAL_READ | off-host checkpoint |
| .planning/phases/01-research-formalization/01-04-SUMMARY.md, 01-04-negative-test-RED.txt | NORMAL_READ | gate evidence |
| .planning/phases/06-*/06-REVIEW-FIX.md | NORMAL_READ | WR-02 |
| .planning/phases/04-*/04-REVIEW-FIX.md | NORMAL_READ | CR-03/CR-05 |
| .planning/phases/09-*/09-REVIEW-DISPOSITION.md, 09-REVIEW-FIX.md, deferred-items.md | NORMAL_READ | WR-07 skipped |
| docs/DECISIONS.md, DOC_STATUS.md, GLOSSARY.md, TECHNOLOGY_STACK.md | DEEP_READ | |
| docs/data/DATA_MODEL.md | NORMAL_READ | entities, §3–6 |
| docs/configuration/CONFIGURATION.md | DEEP_READ | |
| docs/trading/RISK_MANAGEMENT.md, EXECUTION_SPEC.md, SIGNAL_AND_ALERTS.md | DEEP_READ | |
| docs/backtest/BACKTEST_SPEC.md | DEEP_READ | |
| docs/testing/TESTING_STRATEGY.md | NORMAL_READ | |
| docs/integration/TELEGRAM.md, docs/operations/SECURITY_AND_OPERATIONS.md | DEEP_READ | |
| docs/operations/RUNBOOK.md | METADATA_ONLY | headings |
| docs/implementation/IMPLEMENTATION_PLAN.md, docs/00_PRODUCT_SCOPE.md | DEEP_READ | |
| docs/research/RESEARCH_PROTOCOL.md | NORMAL_READ | outline, §1, §3, §4 kill gate |
| docs/research/families/trend-pullback.md, breakout-retest.md | NORMAL_READ | baselines, params, status |
| docs/research/families/range-mr.md | METADATA_ONLY | status lines |
| docs/architecture/ARCHITECTURE.md, DATA_PIPELINE.md | METADATA_ONLY | headings |
| AGENTS.md | DEEP_READ | (in context) |
| .github/workflows/*.yml | DEEP_READ | three workflows; registry-gate re-run by probe |
| pyproject.toml, Dockerfile, docker-compose.yml, .env.example | DEEP_READ | |
| params/**/*.toml | NORMAL_READ | list plus baseline-v3 |
| tests/fixtures/phase4/parameters.json | DEEP_READ | 3 pins |
| tests/fixtures/phase6/intrabar_both_touched/input.json | NORMAL_READ | lookahead evidence |
| src/domain/enums.py, ids.py, signal.py | NORMAL_READ | |
| src/db/models.py | METADATA_ONLY | table names |
| src/execution/enablement.py | DEEP_READ | |
| src/execution/placement.py, manager.py | NORMAL_READ | TP legs, fill attach, TIF |
| src/backtest/simulator.py | NORMAL_READ | run loop 720–870, docstrings |
| src/backtest/experiment.py | NORMAL_READ | record/assemble |
| src/backtest/report.py | NORMAL_READ | slices, bootstrap/drawdown |
| src/core/planner.py | NORMAL_READ | geometry, TP2 |
| src/risk/sizing.py, portfolio.py, quantization.py | NORMAL_READ | via grep and codegraph |
| src/ops/backup.py | NORMAL_READ | drill, defaults, env |
| src/ops/health.py, src/adapters/telegram_notify.py, src/paper/notify.py, src/reconcile/safe_mode.py | METADATA_ONLY | function lists |
| src/adapters/binance_usdm.py | METADATA_ONLY | method list; user-data grep |
| src/execution/fill_monitor.py | NORMAL_READ | header |
| tool-output/*.txt | METADATA_ONLY | tails |
| Remaining src/, tests/ | EXCLUDED | code lanes L2–L8; helpers ran ~258 tests for 02–06 (green) |

## Verified Safe Areas

- **Entry reference consistent between sizing and live LIMIT price.** `src/risk/gating.py:69-79` and `src/execution/placement.py:126-133` both use zone-mid `(entry_min+entry_max)/2`. Live does not size on a different price than the plan.
- **Canonical enums vs GLOSSARY.** The code has exactly the GLOSSARY values for SignalStatus, TradePlanStatus, ApprovalAction, OrderStatus, TradeStatus, PositionStatus, SystemMode, DailyState, KillGateState and RejectionReason (`enum_probe.py`: no extra or missing values). Drift exists only outside the enums (F-110).
- **Kill-gate rule.** D030's conforming wording matches the code enum docs (`src/domain/enums.py:172-186`) and the GLOSSARY §8.2. `enable()` refuses INSUFFICIENT_EDGE and non-evaluated values (`enablement.py:199-208`). The rollout-gating gap is separate (F-105).
- **Uncertainty-first report exists.** `src/backtest/report.py` implements a stationary block bootstrap (lines 96, 464-504) and a resampled drawdown distribution (lines 130-141, 506-544), as BACKTEST_SPEC §10 requires. Caveats: regime slice (F-123) and lookahead-contaminated inputs (F-120).
- **SignalId determinism.** `src/domain/ids.py:19-46` hashes a superset of the SIGNAL_AND_ALERTS §3 tuple (adds strategy_id and parameter_set_id). This is a safe superset.
- **v0.3 audit claims re-verified:** zero production callers for `execute_approved_plan`, `enable(`, `run_paper_tick`, `assemble_paper_record`, `dispatch_callback`, `PaperSupervisor` and `notify_simulate` (grep over src/ and scripts/). This confirms M1–M3. M4 is confirmed as well: `simulator.run` is called only from `experiment.py`, and no Parquet→case_input builder exists.
- **Phase-1 contradiction list (RSCH-03).** DECISIONS D022–D028 exist, with matching GLOSSARY §2.1 (D028), EXECUTION_SPEC §3 (D024) and 00_PRODUCT_SCOPE §7 (D022). One exception is the TESTING_STRATEGY §8 example (F-111).
- **Test suite health.** tool-output/pytest.txt shows 1268 passed and 7 skipped (PG-gated). The helper pass re-ran about 258 phase 02–06 tests, all green. Green tests do not imply correct semantics (F-109, F-120).

## Findings

### F-104 — There is no Binance user-data stream client and no fill/trade query

- **ID:** F-104
- **Severity:** HIGH
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** lost requirement / exchange events
- **Component:** src/adapters/binance_usdm.py, src/execution/fill_monitor.py
- **File:** `src/adapters/binance_usdm.py`
- **Lines:** 526-1256
- **Invariant:** INV (exchange authority / protective confirmation)
- **Phase/commit:** 08, 09 / 63ca176
- **Known-prior:** NEW (v0.3 audit lists composition gaps M1-M4, not the missing event source; ROADMAP Phase 12 mentions user-data only for equity).
- **Summary:** There is no Binance user-data stream client and no fill/trade query. No listenKey, no ORDER_TRADE_UPDATE/ALGO_UPDATE/ACCOUNT_UPDATE parsing, no userTrades. So `attach_protectives_to_fill(fill_events=...)` and `fold_fills` have no production source of fills. The requirement 'user-data WS preferred realtime' (AGENTS, PROJECT constraints, EXECUTION_SPEC §1/§6, PRODUCT_SCOPE §4, 08-CONTEXT D-03) never became a REQ-ID and is not in ROADMAP phases 11-17.
- **Evidence:** binance_usdm.py adapter surface (lines 526-1256); fill_monitor.py:1-10; manager.py:802-860; ops/health.py:378-395; AGENTS.md Exchange Connectivity bullets.
- **Expected:** EXECUTION_SPEC.md:22 'Monitor user-data events'; :89 'After entry fill, verify protective stop exists'; AGENTS 'User-data streams are the preferred realtime source for orders/fills/positions'; 'The reconciler/orphan-sweeper must parse ALGO_UPDATE'; 00_PRODUCT_SCOPE §4 'User-data stream monitoring for orders and positions'.
- **Actual:** grep -i 'listen_key|listenKey|user_data_stream|ORDER_TRADE_UPDATE|ALGO_UPDATE|ACCOUNT_UPDATE' src -> only a docstring (binance_usdm.py:58) and a health-check name that takes injected state (ops/health.py:378). The adapter method list (binance_usdm.py:531-1231) has klines/OI/funding/exchange_info, snapshot_* (REST), query/cancel/place, get_position_mode. It has no fills, account or user-data method. manager.py:802-812 requires caller-provided `fill_events`.
- **Reproduction:** Read the cited lines.
- **Impact:** If the live path is composed as designed, full-size protective legs (TP1/TP2, SL resize) depend on fill events that nothing produces. Only the entry-time close-all SL exists. A partial fill, a TP1 trigger rejection (ALGO_UPDATE.o.rm) or a liquidation would be seen only by periodic REST reconciliation, which is itself unscheduled (v0.3 M2).
- **Why tests miss it:** Every execution test feeds synthetic fill events into the pure functions.
- **Remediation:** Add a REQ-ID and phase for the USD-M user-data stream (listenKey lifecycle, ORDER_TRADE_UPDATE, ALGO_UPDATE incl. o.rm, ACCOUNT_UPDATE). Re-verify the URLs against the 2026-04 /private base-URL split (F-053) and feed fold_fills and the reconciler from it.

### F-120 — The backtest fills and exits trades using the same 1H bar that produced the signal, i.e

- **ID:** F-120
- **Severity:** HIGH
- **Confidence:** CONFIRMED
- **Classification:** DEFECT
- **Category:** backtest lookahead (BKTS-01/DOMN-03 claims)
- **Component:** src/backtest/simulator.py run/_resolve_entry
- **File:** `src/backtest/simulator.py`
- **Lines:** 752-870
- **Invariant:** INV (no-lookahead / closed-candle)
- **Phase/commit:** 06 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 06-VERIFICATION G3 / 06-REVIEW CR-04 (expiry clock) skipped. The same-bar entry/exit lookahead is NEW (not in 06-REVIEW, 06-VERIFICATION or the v0.3 audit).
- **Summary:** The backtest fills and exits trades using the same 1H bar that produced the signal, i.e. with data from before the decision time. The strategy and planner are evaluated on closed bar `bar` (decision at bar.close_time_utc). `_resolve_entry(bar=bar)` then decides the zone touch/fill and the invalidation from that bar's own high/low/open/close, and the exit is resolved from the 1m candles keyed to that same bar (`intrabar_key = f"{bar.symbol}|{bar.close_time_utc}"`, 09:00-09:59 for a 09:59:59 decision). Every trade is also held for at most one bar ('EOD' at the last 1m close). The SUMMARY/VERIFICATION claims that BKTS-01 intrabar resolution and the DOMN-03 no-lookahead suite hold are therefore false for the simulator.
- **Evidence:** Verified by the lane reading simulator.py:745-870 and the fixture; independently reported by the phase 02-06 spot-check helper. tests/test_backtest_simulator.py:366 (Beh-12) only appends a 1m candle after the horizon, so it cannot detect same-bar use.
- **Expected:** BACKTEST_SPEC.md:18-22 'No future candle data ... or future intrabar outcome may leak into historical decisions'; RESEARCH_PROTOCOL §3 closed-candle rule; entry can only fill on bars AFTER the signal close, within expiry; exits after entry.
- **Actual:** simulator.py:756-786 evaluate/plan on sorted_bars[:idx+1] ending at `bar`; :840-847 `_resolve_entry(trade_plan=..., bar=bar, ...)`; _resolve_entry (:449) `zone_touched = bar.high >= trade_plan.entry_min_price and bar.low <= trade_plan.entry_max_price`, (:394,:421) invalidation by `bar.close < bar.open` / `>`; :858 `intrabar_key = f"{bar.symbol}|{bar.close_time_utc.isoformat()}"`. Fixture tests/fixtures/phase6/intrabar_both_touched/input.json: signal bar 09:00:00-09:59:59, intrabar_1m_map key 'BTCUSDT|2026-09-11T09:59:59+00:00' holds 60 candles 09:00:00..09:59:59 (the signal bar itself). Expiry uses the run-level fixture now_utc, not bar time (:725, 06-REVIEW CR-04 skipped).
- **Reproduction:** python: load tests/fixtures/phase6/intrabar_both_touched/input.json; print strategy_bars[-1] times and intrabar_1m_map key/range. The key equals the signal bar close and the candles span the signal bar.
- **Impact:** Every backtest result (and hence family evidence, the kill gate and any go-live decision) is contaminated by lookahead: the fill and outcome are decided by price action that the strategy had already seen. The results are not a valid basis for accepting any family. The fixtures were built to match this behaviour, so the whole suite is green.
- **Why tests miss it:** Golden fixtures encode the same-bar semantics; the no-lookahead suites (DOMN-03) target strategy.evaluate, not the simulator's entry/exit loop.
- **Remediation:** Walk subsequent bars after the signal bar for entry (until expiry/invalidation), then walk 1m data from the fill time forward for the exit, holding across bars. Add a test where the signal bar's own range touches SL/TP and assert no fill on that bar. Re-verify BKTS-01 and discard any evidence produced so far.

### F-126 — EXEC-03 and Phase 8 SC4 ('retries, restarts and replayed events never create duplicate entry orders') are claimed, but approval consumption 

- **ID:** F-126
- **Severity:** HIGH
- **Confidence:** PROBABLE
- **Classification:** GAP
- **Category:** EXEC-03 / Phase 8 SC4 overstated
- **Component:** src/execution/manager.py execute_approved_plan
- **File:** `src/execution/manager.py`
- **Lines:** 162-240
- **Invariant:** INV (idempotent approval / no duplicate entry)
- **Phase/commit:** 08, 09 / 63ca176
- **Known-prior:** PARTIAL KNOWN: in-code NOTE. NEW: the requirement/SC is marked satisfied while the mechanism is missing.
- **Summary:** EXEC-03 and Phase 8 SC4 ('retries, restarts and replayed events never create duplicate entry orders') are claimed, but approval consumption is explicitly not implemented. Deterministic clientOrderIds only deduplicate against the exchange while the first order is still open. After it fills or is canceled, re-running execute_approved_plan for the same approval (an at-least-once Telegram replay, or a restart) re-places the entry.
- **Evidence:** Lane verified manager.py:234-240; the Binance clientOrderId uniqueness scope (open orders) is per A2 lane / exchange docs, so the verdict is PROBABLE.
- **Expected:** TELEGRAM.md §3/§6 'Replaying an old approval must not place a fresh order'; EXECUTION_SPEC §7; ROADMAP Phase 8 SC4.
- **Actual:** manager.py:237-239 'NOTE: consuming the approval ... needs persisted execution state and is NOT handled here.'; manager.py:162-204 places first and probes only on ambiguity; approval replay protection (approval/replay.py) is in-process only (helper: comment at replay.py:48-53, no conditional UPDATE).
- **Reproduction:** Read the cited lines.
- **Impact:** A duplicate live position at full risk once live is composed. This is a money-loss path.
- **Why tests miss it:** Replay tests use in-memory state and an open (unfilled) order.
- **Remediation:** Persist execution state keyed by approval_id/plan_hash with a unique constraint; execute only on the first transition, and replay the stored outcome afterwards.

### F-101 — The three CI gates that the docs and plans cite as 'enforced by gate, not convention' never execute (origin is a local path, no GitHub), and

- **ID:** F-101
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** governance/CI
- **Component:** .github/workflows (research-gate, registry-gate, paper_freeze_check)
- **File:** `.github/workflows/registry-gate.yml`
- **Lines:** 31-80
- **Invariant:** INV (registry immutability / protocol freeze)
- **Phase/commit:** 01, 03, 07 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 01-VERIFICATION human_needed (branch protection, no remote). NEW: registry-gate red on HEAD, tripwire/identity vacuity caused by the Phase-3 TOML decision, PAPER-03 artifact never produced.
- **Summary:** The three CI gates that the docs and plans cite as 'enforced by gate, not convention' never execute (origin is a local path, no GitHub), and would not work if they did: registry-gate fails on HEAD (7 of 10 params TOMLs have no pin), and the research-gate registry tripwire and identity check are permanently vacuous because the registry was built as TOML under params/, not JSON/YAML under docs/research/registry/.
- **Evidence:** registry-gate.yml:43-76 (loads tests/fixtures/phase4/parameters.json, fails on 'no pinned hash'); tests/fixtures/phase4/parameters.json:1-22 (3 pins); git log params (v2/v3 added 2026-09-24..26 in 177fd57, d6bdad4) without pin update; research-gate.yml:99-128 tripwire path docs/research/registry; docs/DECISIONS.md:34 (D029); 01-04-SUMMARY.md:235,267 (remote absent, 'manual follow-up').
- **Expected:** ROADMAP Phase 1 SC4: 'A parameter run attempted without a frozen protocol and registered parameter set is rejected by gate, not by convention'. D029: 'Executable gate at .github/workflows/research-gate.yml reads all three witnesses on every PR/push'. PAPER-03 acceptance artifact = registry_diff.jsonl produced by the hourly paper_freeze_check workflow (07-04).
- **Actual:** `git -C snapshot remote -v` -> `origin C:/Users/admin/Music/Trading` (local path; GitHub Actions can never run). Probe tmp/requirements_docs_plan/registry_gate_probe.py re-running the registry-gate Python block on the snapshot prints 7 'no pinned hash' failures (breakout-retest v2/v3, range-mr v2, trend-pullback baseline-no-trade-v1, baseline-simple-trend-v1, v2, v3) and exit 1; tests/fixtures/phase4/parameters.json pins only the three baseline-v1 sets. research-gate.yml:61-80 scans experiment*/backtest*.json|yaml (none exist; zero hits) and :99-128 scans JSON/YAML for parameter sets outside docs/research/registry (params are .toml under params/, zero hits) -> both checks 'pass vacuously' forever. paper_freeze_check.yml (hourly cron, PAPER-03) likewise cannot run, so the PAPER-03 acceptance artifact has never been produced. No backtest path in src/ checks the protocol freeze at run time (grep FROZEN in src/ hits only analytics/clock.py).
- **Reproduction:** cd snapshot; PYTHONPATH=. python -B ../tmp/requirements_docs_plan/registry_gate_probe.py -> 7 failures, exit 1.
- **Impact:** Research-integrity controls that the kill gate, PAPER-03 and D029 rely on are paper-only. baseline-v3 (the canonical paper-soak/cost-binding set) has never been checked against a pin by any gate. Plans and verifications recorded these gates as satisfied.
- **Why tests miss it:** tests/test_registry_gate.py exercises verify_parameter_set, not the workflow's pin coverage; workflows are never executed locally.
- **Remediation:** Either run the gates locally as a pre-commit/`uv run` task (and pin every params TOML), or stop citing them as enforcement. Retarget the research-gate tripwire/identity checks to params/**/*.toml and the snake_case experiment fields; add a runtime freeze check to the backtest/experiment entry point.

### F-102 — Backtest exits the whole position at TP1 ('single-exit scope'), while live execution splits the position into TP1 (reduce-only fraction) plu

- **ID:** F-102
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** backtest-live parity
- **Component:** src/backtest/simulator.py vs src/execution/placement.py
- **File:** `src/backtest/simulator.py`
- **Lines:** 116-126
- **Invariant:** -
- **Phase/commit:** 06, 09 / 63ca176
- **Known-prior:** KNOWN (as limitation): 06-REVIEW WR-02. NEW: the 'conservative' justification is false and live implements the ladder, so it is a parity break, not a scope note.
- **Summary:** Backtest exits the whole position at TP1 ('single-exit scope'), while live execution splits the position into TP1 (reduce-only fraction) plus TP2 (close-all at 2x the TP1 leg) with the SL unchanged. The code and 06-REVIEW-FIX call the TP1-only exit 'conservative', but it is path-dependent and optimistic in the TP1-then-SL case, so the evidence does not describe the live exit policy.
- **Evidence:** 06-REVIEW-FIX.md:175-184 (WR-02 'TP2 silently dropped' resolved by documenting 'TP1 exit is conservative'); simulator.py:104,120-126,207-211; planner.py:395-400; placement.py:340-345,396-421.
- **Expected:** AGENTS/PROJECT core constraint: identical semantics backtest/paper/live; BACKTEST_SPEC §13 'final validation path must execute the canonical engine' with the same execution semantics.
- **Actual:** simulator.py:120-126 'Single-exit scope: the planner's TP2 runner leg is not modeled — a fill exits wholly at the first touched level (TP1), which is conservative'; simulator.py:207-211 same. planner.py:395-400 builds TP2 = entry ± 2·(TP1−entry); placement.py:343-344 one-way: SL closePosition, TP1 explicit qty reduce_only, TP2 closePosition; manager.py:938-939 places TP1 and TP2 legs. Worked example with TP1 at 2R (minimum_rr=2.0), fraction 0.5: path TP1→SL: live = 0.5·2R − 0.5·1R = +0.5R, backtest = +2.0R (overstates by 1.5R); path TP1→TP2: live = 0.5·2R + 0.5·4R = +3R, backtest = +2R.
- **Reproduction:** Read the cited lines.
- **Impact:** Backtest expectancy (the kill-gate and family-selection evidence) is biased in an unknown direction relative to what live would do; for pullback/reversal paths it is optimistic. A family could be passed on evidence its live exit policy does not reproduce.
- **Why tests miss it:** Backtest tests pin simulator fixtures; execution tests pin leg shapes; no parity test compares realized R between the two for the same path.
- **Remediation:** Pick one exit policy and implement it in both engines (either model the TP1/TP2 ladder in the simulator, or place a single TP in live). Record the choice in DECISIONS.md.

### F-103 — The TP1 split fraction (`tp1_quantity_fraction`), the TP2 extension rule (2x TP1 leg) and the entry time-in-force (GTC) change trade outcome

- **ID:** F-103
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** parameter registry
- **Component:** src/execution/placement.py ProtectiveTemplate
- **File:** `src/execution/placement.py`
- **Lines:** 49-76
- **Invariant:** -
- **Phase/commit:** 09 / 63ca176
- **Known-prior:** NEW
- **Summary:** The TP1 split fraction (`tp1_quantity_fraction`), the TP2 extension rule (2x TP1 leg) and the entry time-in-force (GTC) change trade outcomes but are not registered parameters. The fraction is caller-supplied, only tests set it (0.5), and nothing in src/ or params/ defines it.
- **Evidence:** placement.py:49-76; manager.py:515; planner.py:395-400; 09-CONTEXT.md discretion bullet.
- **Expected:** CONFIGURATION.md §1 'Every strategy parameter that can affect a signal or trade plan must be versioned'; §4 'A live order must never use an unregistered parameter set'.
- **Actual:** placement.py:59 `tp1_quantity_fraction: Decimal` field of ProtectiveTemplate; grep over src/ and params/ finds no producer; tests/fixtures/phase9/*/input.json set "0.5". planner.py:398-400 hard-codes `_q("2")` for TP2. manager.py:515 hard-codes `"time_in_force": "GTC"`. 09-CONTEXT 'Agent's Discretion' left 'TP1/TP2 split mechanics, entry-zone limit-price policy details (zone edge vs mid, time-in-force)' to the implementer.
- **Reproduction:** Read the cited lines.
- **Impact:** Live P/L depends on values outside the parameterSetHash, which breaks reproducibility and the plan-hash/approval binding (the human approves a plan whose exit split is not in the hash).
- **Why tests miss it:** Tests inject the fraction directly.
- **Remediation:** Add tp1 fraction, TP2 multiple and time-in-force to the registry whitelist, include them in plan_hash, and derive ProtectiveTemplate from the registered set.

### F-105 — The documented prerequisites for live trading are not REQ-IDs and are not enforced

- **ID:** F-105
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** rollout gating
- **Component:** src/execution/enablement.py
- **File:** `src/execution/enablement.py`
- **Lines:** 147-219
- **Invariant:** -
- **Phase/commit:** 09, 10 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 10-REVIEW WR-10 'enable() trusts caller' (the state is caller-supplied). NEW: even an honest evaluated WITHIN_BUDGET enables live, and the rollout prerequisites were never traced into requirements.
- **Summary:** The documented prerequisites for live trading are not REQ-IDs and are not enforced. `enable()` accepts KillGateState.WITHIN_BUDGET, the default state while research is still running and no family has passed. Nothing requires a passing family, D012 decided, the paper exit gate, runbook-exercised evidence or a capital cap before live orders are enabled.
- **Evidence:** enablement.py:147-219; src/domain/enums.py:172-186; DECISIONS.md:12,16; IMPLEMENTATION_PLAN.md:79-125; ROADMAP.md Phase 8 'Depends on' note, Phase 9 SC3.
- **Expected:** D008 'Backtest before paper/live'; IMPLEMENTATION_PLAN.md:94-101 Phase 2 (paper) exit gate: minimum forward evidence, no unexplained gaps, no paper/backtest divergence, runbook exercised; :117 'smallest capital'; ROADMAP Phase 8 'enablement gates on paper evidence'; Phase 9 SC3 'first orders only on smallest capital'; GLOSSARY §8.2: PASSING_CANDIDATE 'does not authorize live' (and WITHIN_BUDGET a fortiori should not).
- **Actual:** enablement.py:199-208 only rejects non-KillGateState values and INSUFFICIENT_EDGE, so WITHIN_BUDGET and PASSING_CANDIDATE both pass. It checks only operator id, timestamp and health verdict. grep 'smallest capital|max_equity|capital_cap|max_notional' over src/ and params/ finds nothing. D012 (V1 family) is still 'TBD' (DECISIONS.md:16).
- **Reproduction:** Read the cited lines.
- **Impact:** Once a composer exists (v0.3 M1/M2), an operator can enable live on an unvalidated strategy with any account size, and the code gives no refusal. The safety rests on human discipline, contrary to 'rejected by gate, not by convention'.
- **Why tests miss it:** test_execution_enablement covers only INSUFFICIENT_EDGE / unevaluated refusal.
- **Remediation:** Create REQ-IDs for the live-enablement prerequisites. Make enable() require a recorded human family-selection decision (D012) plus a paper-evidence record, and a configured max-equity/notional cap for the first rollout.

### F-106 — There are no operational alerts

- **ID:** F-106
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** lost requirement / alerting
- **Component:** src/adapters/telegram_notify.py, src/risk/portfolio.py, src/reconcile/safe_mode.py
- **File:** `src/adapters/telegram_notify.py`
- **Lines:** 58-211
- **Invariant:** -
- **Phase/commit:** 05, 08, 09 / 63ca176
- **Known-prior:** NEW.
- **Summary:** There are no operational alerts. The docs require high-priority alerts (unprotected position, local vs Binance divergence, unknown order, duplicate attempt, stale data, rejected protective action, auth failure), 'alert the user' on DAILY_STOP, 'alert fires' on WARNING, and 'ALERT HIGH PRIORITY' when protection cannot be confirmed. None of these has a REQ-ID or code. The only Telegram senders are SIMULATE/APPROVE and a health probe message.
- **Evidence:** grep send_message src -> telegram_notify.py:74 (send_simulate) and ops/health.py:513 only; 05-VERIFICATION marks RISK-02 SATISFIED without the alert.
- **Expected:** SECURITY_AND_OPERATIONS.md:120-130 §5 Alerts; RISK_MANAGEMENT.md:81-85 'alert the user'; GLOSSARY.md:135 WARNING '(alert fires)'; EXECUTION_SPEC.md:91-96; 05-CONTEXT D-03 'DAILY_STOP blocks new entries, leaves existing protectives active, raises alert'.
- **Actual:** telegram_notify.py defines send_simulate, build_*_keyboard and format_approve only; paper/notify.py has format_simulate/notify_simulate; ops/health.py:490-520 sends a probe text. portfolio.py:361-365 returns DAILY_STOP_BLOCK with no notification; safe_mode.enter_safe_mode (safe_mode.py:176) only journals.
- **Reproduction:** Read the cited lines.
- **Impact:** SAFE_MODE, DAILY_STOP, an unprotected position or reconciliation drift would be silent to a user who by design does not watch the system continuously. The runbook procedures assume the user is alerted.
- **Why tests miss it:** No requirement, so no test.
- **Remediation:** Add an OPS REQ-ID for the §5 alert catalogue and an alert adapter invoked from SAFE_MODE entry, DAILY_STOP/WARNING transitions, protective-confirmation failure and health RED.

### F-107 — The Phase 2 goal 'OI accumulates from day one' is not met in reality

- **ID:** F-107
- **Severity:** MEDIUM
- **Confidence:** PROBABLE
- **Classification:** GAP
- **Category:** data foundation / irrecoverable data
- **Component:** src/data/collector.py, docker-compose.yml
- **File:** `.planning/phases/02-data-foundation/02-VERIFICATION.md`
- **Lines:** 22-34
- **Invariant:** -
- **Phase/commit:** 02 / 63ca176
- **Known-prior:** KNOWN as human_needed (02-VERIFICATION, v0.3 tech_debt). NEW: the requirement verdict 'satisfied' contradicts the phase goal; no tracked item forces the deployment.
- **Summary:** The Phase 2 goal 'OI accumulates from day one' is not met in reality. The collector was never deployed (Docker engine absent, live-network run never done), yet the phase is counted complete and the v0.3 audit marks DATA-01..04 'satisfied'. The 30-day OI API window keeps discarding data that D009/D017 call irrecoverable.
- **Evidence:** 02-VERIFICATION.md:1-34; v0.3-MILESTONE-AUDIT.md:231-236,tech_debt 02; docker-compose.yml app service; Dockerfile CMD collector.
- **Expected:** ROADMAP Phase 2 goal + SC2; DATA-02 'collects OI snapshots continuously from Phase 0'; IMPLEMENTATION_PLAN.md:48 exit gate 'OI collector is running continuously'.
- **Actual:** 02-VERIFICATION.md:22-33 human_verification: 'Docker daemon not running', 'Live-network bootstrap never executed', 'Collector proven via unit tests only; long-running deployment needs Compose PG + scheduler wiring'. No data/ directory exists in the original working tree. v0.3-MILESTONE-AUDIT.md Requirements table: 'DATA-01..04 | satisfied (update checkbox)'. STATE.md completed_phases counts phase 2. Compose never runs `alembic upgrade`, so the collector's tables would not exist on first start. Dockerfile:33 HEALTHCHECK runs bare `python -m src.data.collector --healthcheck`, but dependencies live in /app/.venv (UV_PROJECT_ENVIRONMENT, not on PATH) and collector.py imports polars/structlog/sqlalchemy at module top (lines 53-56). The probe would therefore fail with ImportError and the container would always report unhealthy (PROBABLE, reasoned, not run).
- **Reproduction:** Read the cited lines.
- **Impact:** Every day without the collector permanently loses OI history (one of the few inputs the project says cannot be rebuilt). Research on REFN-02 and Stage D context features is starved.
- **Why tests miss it:** Collector tests use fakes; deployment is an operator step.
- **Remediation:** Re-classify DATA-02/DATA-04 as PARTIAL until the collector runs and one real backup/restore drill passes. Make starting the collector the top operator action.

### F-108 — Backups are not off-host, not encrypted, not scheduled and have no retention policy, contrary to the docs and DATA-04

- **ID:** F-108
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** backup/restore
- **Component:** src/ops/backup.py, .env.example, docker-compose.yml
- **File:** `src/ops/backup.py`
- **Lines:** 28-59
- **Invariant:** -
- **Phase/commit:** 02 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 02-VERIFICATION human item 4 (live pg_dump drill). NEW: target/encryption/retention drift and orchestrator-closed checkpoint.
- **Summary:** Backups are not off-host, not encrypted, not scheduled and have no retention policy, contrary to the docs and DATA-04. The default target is `data/backup` (a Docker named volume on the same host). The module docstring says the target comes from `BACKUP_TARGET`, but the Python CLI never reads that variable. The 02-05 'off-host' human-verify checkpoint was closed by the orchestrator, not by the human.
- **Evidence:** as above
- **Expected:** SECURITY_AND_OPERATIONS.md:171-176 'automated backup; encrypted copy outside the primary runtime host; documented retention; periodic restore verification'; TECHNOLOGY_STACK.md:58 'PostgreSQL backup must be external to the primary runtime host'; DATA-04.
- **Actual:** backup.py:59 `DEFAULT_BUNDLE_ROOT = Path("data") / "backup"`; backup.py:505,526,540 CLI default; os.environ reads only PG_DUMP_BIN/DATABASE_URL (backup.py:465-466); .env.example:32 `OFF_HOST_BACKUP_TARGET=data/backup`; docker-compose.yml `backupdata:/app/data/backup` named volume; no encryption/retention code (grep encrypt|retention -> none); 02-05-SUMMARY.md:286-293 'The orchestrator confirmed... No fresh human-verify gate was emitted'.
- **Reproduction:** Read the cited lines.
- **Impact:** Losing the host loses both the database and its backup, including self-collected OI and the journal (which SECURITY §9 treats as a data-loss incident).
- **Why tests miss it:** Drill tests use a tmpdir and fake pg_dump runner.
- **Remediation:** Make the backup target required (no on-host default), read it in the Python CLI, add encryption and retention, and schedule the job.

### F-109 — 05-VERIFICATION marks SC1/RISK-01 'VERIFIED … including modeled costs', based on self-authored parity fixtures and 'hand-verified' tables

- **ID:** F-109
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** verification reliability
- **Component:** .planning/phases/05-risk-engine/05-VERIFICATION.md
- **File:** `.planning/phases/05-risk-engine/05-VERIFICATION.md`
- **Lines:** 44-128
- **Invariant:** -
- **Phase/commit:** 05 / 63ca176
- **Known-prior:** KNOWN bug: ROADMAP Phase 11 (backlog 999.5). NEW: the verification verdict is wrong and should be reopened; the v0.3 requirement scores built on it are inflated.
- **Summary:** 05-VERIFICATION marks SC1/RISK-01 'VERIFIED … including modeled costs', based on self-authored parity fixtures and 'hand-verified' tables. The unit bug later found in `modeled_costs_per_unit` (rate added to a price distance) shows the verification checked self-consistency, not the requirement. The v0.3 audit then counts phases 04/05 as verified from these reports. The same pattern applies to D-03's 'raises alert', which was accepted without code.
- **Evidence:** 05-VERIFICATION.md:44,96,128; ROADMAP.md Phase 11 goal; src/risk/sizing.py:59-60; src/backtest/costs.py:184.
- **Expected:** VERIFICATION verdicts that a money requirement holds should rest on an independent oracle (units/dimension check, hand calculation in quote currency).
- **Actual:** 05-VERIFICATION.md:44 'risk_per_unit = SL_distance + modeled_costs … Parity table hand-verified'; :96 RISK-01 SATISFIED; :128 'No gaps'. ROADMAP Phase 11 goal (2026-09-29): 'returns the rate sum … adds it to an SL distance in quote currency … costs are effectively ignored'. 05-CONTEXT.md:24 D-03 requires an alert; no alert exists (F-106).
- **Reproduction:** Read the cited lines.
- **Impact:** Downstream audits and the user treat 'passed' verification as evidence. At least one money-critical requirement was passed while wrong, so the other 'passed' phases (04, 07.1) carry the same epistemic risk.
- **Why tests miss it:** Fixture expectations were generated by the same code/assumption.
- **Remediation:** Re-open RISK-01 as PARTIAL until Phase 11. Add dimensional/independent-oracle checks to the verification template for money paths.

### F-111 — No state-machine transition validation exists anywhere in src/

- **ID:** F-111
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** lost requirement / state machines
- **Component:** src/domain/*
- **File:** `docs/data/DATA_MODEL.md`
- **Lines:** 355-362
- **Invariant:** -
- **Phase/commit:** 03 / 63ca176
- **Known-prior:** NEW.
- **Summary:** No state-machine transition validation exists anywhere in src/. DATA_MODEL §5 'State transitions must be validated in application code' and TESTING_STRATEGY §8 invalid-transition tests never became a requirement or code. The TESTING_STRATEGY §8 examples are also wrong: they use a non-existent TradePlanStatus CANCELED and a 'NEW PROTECTIVE ORDER' pseudo-state, and this survived the Phase-1 C3 edit of that same section.
- **Evidence:** as above; 01-03-SUMMARY (C3 edit of TESTING_STRATEGY §8).
- **Expected:** DATA_MODEL.md §5; TESTING_STRATEGY.md:107-117; ARCHITECTURE §5 'explicit state machines'; TECHNOLOGY_STACK.md:26 'typed domain models and explicit state machines'.
- **Actual:** grep 'ALLOWED_TRANSITIONS|_TRANSITIONS|def transition|InvalidTransition' src -> none; no invalid-transition test (only approval replay single-transition tests). TESTING_STRATEGY.md:112 'TradePlanStatus: CANCELED → APPROVED' vs GLOSSARY.md:58-65 (no CANCELED). TradeStatus enum is defined but never used outside enums/__init__.
- **Reproduction:** Read the cited lines.
- **Impact:** Nothing prevents e.g. EXPIRED→APPROVED on a signal/plan row or a protective order for a CLOSED trade, except ad-hoc checks in individual functions. DOMN-01 was verified without this rule.
- **Why tests miss it:** No requirement, so no suite.
- **Remediation:** Add per-entity transition tables and a validator used by mappers/writers. Fix the TESTING_STRATEGY §8 examples to canonical values.

### F-112 — DATA_MODEL defines 12 entities; DOMN-01 narrowed this to 7, taken from the §1 chain, which itself omits `Trade`, although §4 requires Trade 

- **ID:** F-112
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** lost requirement / data model
- **Component:** src/db/models.py, src/domain/signal.py
- **File:** `docs/data/DATA_MODEL.md`
- **Lines:** 1-353
- **Invariant:** -
- **Phase/commit:** 03, 06 / 63ca176
- **Known-prior:** PARTIAL KNOWN: v0.3 M4 (no Parquet→backtest input). NEW: entity/requirement narrowing.
- **Summary:** DATA_MODEL defines 12 entities; DOMN-01 narrowed this to 7, taken from the §1 chain, which itself omits `Trade`, although §4 requires Trade 1..N Order. Never implemented: `trades` (net_pnl, commission, funding, realized_R), `feature_snapshots` (and Signal.feature_snapshot_id/regime from SIGNAL_AND_ALERTS §2), `experiment_runs`, and the DB parameter registry (CONFIGURATION §6). There is no DECISIONS record for dropping them.
- **Evidence:** as above
- **Expected:** DATA_MODEL.md §2.2, §2.6, §2.12, §4 (TradePlan 1..0..1 Trade; Trade 1..N Order); SIGNAL_AND_ALERTS.md:25-45 (Regime, FeatureSnapshotId, RiskRate, ExpectedRR on Signal); CONFIGURATION.md:86-98 DB registry.
- **Actual:** src/db/models.py tables: symbol_metadata, collector_watermarks, collector_gaps, coverage_windows, signals, trade_plans, approvals, orders, fills, positions, journal_events, short_id_mapping. There is no trades, feature_snapshots, experiment_runs or parameter_sets table. src/domain/signal.py:46-59 has no regime/feature_snapshot_id. ExperimentRecord is built in memory (experiment.py:170-243) and has no writer in src/ or scripts/.
- **Reproduction:** Read the cited lines.
- **Impact:** The Core Value 'explainable from market data' has no persisted feature snapshot. User-performance reporting (DATA_MODEL §6 Signal→Approval→Order→Fill→Position) has no trade-level net PnL/realized R row. Experiment reproducibility depends on files nobody writes.
- **Why tests miss it:** Requirement text only names seven entities.
- **Remediation:** Either record a DECISIONS entry that descopes these entities, or add REQ-IDs. At minimum persist ExperimentRecord and the feature snapshot hash.

### F-113 — The implemented family geometries do not match the family sheets' mandatory Stage baselines, and there is no DECISIONS entry

- **ID:** F-113
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** strategy spec vs code
- **Component:** src/core/planner.py
- **File:** `src/core/planner.py`
- **Lines:** 97-135
- **Invariant:** -
- **Phase/commit:** 04 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 04-REVIEW CR-03/CR-05 (fix applied). NEW: divergence from the sheets not recorded, sheets stale.
- **Summary:** The implemented family geometries do not match the family sheets' mandatory Stage baselines, and there is no DECISIONS entry. Family A Stage A requires T1 (fixed-R TP); the code uses TP1 = opposing swing high (T2-like). Family B Stage B requires S3 (zone invalidation on the other side of the broken zone) and T1; the code puts the stop just under the retest edge ('a support-based stop ... would NO_TRADE every plan') with a measured-move TP. TP2 = 2x TP1 appears in no sheet. All three sheets still say 'Stage baseline implemented: NO'.
- **Evidence:** as above
- **Expected:** trend-pullback.md:58 'Stage A baseline | R1 + P1 + E2 + S2 + T1 (fixed-R TP) | Reference; never removed'; breakout-retest.md:62 'Stage B baseline | B1 + R1 + E2 + S3 + T1'; RESEARCH_PROTOCOL R1-R6 (no post-hoc changes to make a gate pass).
- **Actual:** planner.py:107-116 (Family A TP1 = swing_high), :117-131 (Family B stop = zone_upper − sl_buffer, TP1 = zone_upper + height, comment explaining the stop was moved so RR can pass), :395-400 TP2; 04-REVIEW-FIX.md:55-66 CR-03 (and 2e19c5a 'Family B stop correction'); trend-pullback.md:228, breakout-retest.md:245, range-mr.md:247 'implemented: NO'.
- **Reproduction:** Read the cited lines.
- **Impact:** Backtest evidence for the 'independently specified families' (kill-gate input, D030 uses sheet content hashes) comes from rules that are not the frozen sheets. Moving a stop so that the RR gate passes is a data-free design change of the kind R1-R6 forbid to be undocumented.
- **Why tests miss it:** Fixtures were regenerated from the new geometry (1c3c187).
- **Remediation:** Record the geometry as explicit variant IDs in the family sheets (or implement the sheet baselines), add a DECISIONS row, and update the 'implemented' status lines. Ask the B1 lane whether the Family B stop change is sound.

### F-115 — Known safety and money defects left 'pending a design decision' have no ROADMAP or backlog item (phases 11-17 do not cover them): 09-REVIEW 

- **ID:** F-115
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** untracked safety decisions
- **Component:** .planning/phases/09*, 10*
- **File:** `.planning/phases/09-live-execution-rollout/09-REVIEW-FIX.md`
- **Lines:** 268-280
- **Invariant:** -
- **Phase/commit:** 09, 10 / 63ca176
- **Known-prior:** KNOWN: 09-REVIEW WR-07, CR-04; 10-REVIEW dispositions. NEW: not tracked in the roadmap.
- **Summary:** Known safety and money defects left 'pending a design decision' have no ROADMAP or backlog item (phases 11-17 do not cover them): 09-REVIEW WR-07 (entry expiry leaves the close-all SL live, which in one-way mode can close another plan's position; emergency close cancels SL/TP before the position is flat); 09-REVIEW CR-04 (TP1 not resized on later partial fills); 10-REVIEW WR-01/06/10/12/13 'awaiting human decision'.
- **Evidence:** as above
- **Expected:** Every skipped/deferred review finding with money or safety impact gets a tracked backlog/phase item before live enablement.
- **Actual:** 09-REVIEW-DISPOSITION.md:70-73 WR-07 'skipped'; 09-REVIEW-FIX.md:268-280 reason 'needs a design decision'; manager.py:836-839 'resizing TP1 on later partial fills ... is a pending design decision (09-REVIEW CR-04)'; v0.3-MILESTONE-AUDIT.md tech_debt phase 10. ROADMAP phases 11-17 goals contain none of these.
- **Reproduction:** Read the cited lines.
- **Impact:** These are the kind of defects that cause unprotected or wrongly closed positions. Tracking lives only in review files that future phases do not read.
- **Why tests miss it:** -
- **Remediation:** Add backlog/phase items for WR-07 and CR-04 (and the 10-REVIEW decisions) and make them blockers for live enablement.

### F-116 — Several MUST-level doc requirements never became REQ-IDs and are not implemented

- **ID:** F-116
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** lost requirements
- **Component:** REQUIREMENTS.md vs docs
- **File:** `.planning/REQUIREMENTS.md`
- **Lines:** 9-62
- **Invariant:** -
- **Phase/commit:** init / 63ca176
- **Known-prior:** PARTIAL KNOWN: v0.3 audit notes zero production callers for drills/reconciler. NEW: requirement-level loss.
- **Summary:** Several MUST-level doc requirements never became REQ-IDs and are not implemented. RISK §6 (never silently widen a protective stop) and §7 (no revenge/compensation sizing) are covered only incidentally. RISK §12 (store the exact constraint snapshot used for sizing), SECURITY §8 (restart sequence: reconcile before resume), §10 (runtime version and git revision in health output), §1 (encrypt secrets at rest; separate paper/test from live credentials), and EXECUTION_SPEC §11 (manual emergency controls) exist only as library functions with no operator surface. PROJECT 'Core Docs audit with contradictions/gaps explicitly listed' was narrowed in RSCH-03 to 5 pre-known contradictions.
- **Evidence:** SECURITY_AND_OPERATIONS.md:74-82,155-167,183-189; RISK_MANAGEMENT.md:61-69,129-143; EXECUTION_SPEC.md:142-149; PROJECT.md:19; REQUIREMENTS.md:15.
- **Expected:** Every canonical-doc MUST maps to a REQ-ID or an explicit descoping decision.
- **Actual:** REQUIREMENTS.md v1 list (30 IDs) has no IDs for these. src/ has no restart orchestrator (entry points: analytics.cli, data.collector, data.coverage, ops.backup, paper.freeze only). emergency_manual_close (manager.py:1230) and SafeModeController.enter_safe_mode (safe_mode.py:176) have no CLI. health.py has no version/revision output. code_version in ExperimentRecord is a free caller string (experiment.py:176).
- **Reproduction:** Read the cited lines.
- **Impact:** The operator has no supported way to run the RUNBOOK emergency steps against a live process, and restarts are not guaranteed to reconcile before resuming.
- **Why tests miss it:** -
- **Remediation:** Add OPS/EXEC REQ-IDs (restart sequence, emergency CLI, constraint-snapshot persistence, version in health) or record deliberate descoping in DECISIONS.

### F-121 — The DATA-04 'restore drill' never restores PostgreSQL

- **ID:** F-121
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** SUMMARY claim overstated (DATA-04)
- **Component:** src/ops/backup.py run_drill
- **File:** `src/ops/backup.py`
- **Lines:** 17-392
- **Invariant:** -
- **Phase/commit:** 02 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 02-VERIFICATION human_needed item 4, 02-REVIEW CR-06 (fixed runner). NEW: the drill design never restores; the SUMMARY claim is overstated.
- **Summary:** The DATA-04 'restore drill' never restores PostgreSQL. run_drill copies the pg.dump file into a scratch dir and compares sha256 hashes ('the actual pg_restore is left to the operator's environment for V1'). The '02-05 drill-OK exit 0' evidence was produced while the CLI still archived a SQLite probe (02-REVIEW.iter2 CR-06), and no live-PG drill has run since. REQUIREMENTS/v0.3 still count DATA-04 as satisfied.
- **Evidence:** as above (helper report; the lane confirmed lines 17-21 and 380-392).
- **Expected:** DATA-04 'passes an automated backup + restore drill covering PostgreSQL state'; SECURITY §9 'periodic restore verification'; IMPLEMENTATION_PLAN exit gate 'backup/restore smoke test passes'.
- **Actual:** backup.py:17-21 docstring; :387 `shutil.copy2(bundle_pg_dump, restore_pg_dump)`; tests/test_backup.py uses a fake SQLite pg_dump_runner; 02-05-SUMMARY.md:227,314 cite drill-OK; 02-REVIEW.iter2.md:186-193 CR-06 'always prints backup-OK while archiving zero PostgreSQL state'; 02-VERIFICATION.md:33-35 live-PG drill still human_needed.
- **Reproduction:** Read the cited lines.
- **Impact:** Restore capability, the precondition for the RUNBOOK 'restore' drill and for trusting the journal, is unproven. A corrupt or incompatible dump would only be found during an incident.
- **Why tests miss it:** Hash equality of a copy is tautological.
- **Remediation:** Make the drill pg_restore into a scratch database and run row-count/checksum queries. Mark DATA-04 PARTIAL until it passes against real PG17.

### F-124 — Plans stuck on blocking-human checkpoints are shown as complete, and one-way-door decision checkpoints were cleared by the auto-executor ins

- **ID:** F-124
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** human gates bypassed / completion overstated
- **Component:** .planning ROADMAP + SUMMARY checkpoints
- **File:** `.planning/phases/09-live-execution-rollout/09-04-SUMMARY.md`
- **Lines:** 107-266
- **Invariant:** -
- **Phase/commit:** 08, 09, 10 / 63ca176
- **Known-prior:** PARTIAL KNOWN: v0.3 audit notes missing VERIFICATION for 08/09. NEW: blocked/halted plans shown complete; auto-cleared one-way checkpoints.
- **Summary:** Plans stuck on blocking-human checkpoints are shown as complete, and one-way-door decision checkpoints were cleared by the auto-executor instead of a human. 09-04 is `status: blocked` (testnet rehearsal, credential provisioning and LIVE-TAP clearance NOT EXECUTED) and 08-02 is `status: halted` (LIVE-TAP pending), yet ROADMAP marks both [x], Phase 8 'Complete 2026-09-27', Phase 9 '4/4 plans executed', and REQUIREMENTS checks APRV-01. 09-01 recorded 'ACK-ONE-WAY: operator=auto-executor' and 'Auto-selected first option for checkpoint:decision'. 10-05 records 'Decision checkpoint (Task 1) auto-approved'.
- **Evidence:** as above; STATE.md:212,251-252 (per helper) also record the pending gates.
- **Expected:** Checkpoints of type blocking-human (live order permanence, credential/LIVE-TAP, kill-gate event contract) require the user. The ROADMAP/REQUIREMENTS status reflects blocked/halted plans.
- **Actual:** 09-04-SUMMARY.md:107 'status: blocked', :139 and :240 'NOT EXECUTED'; 08-02-SUMMARY.md:178 'status: halted'; ROADMAP.md Phase 8 [x] 'completed 2026-09-27', 09-04 [x]; 09-01-SUMMARY.md:25-26; 10-05-SUMMARY.md:52; REQUIREMENTS.md:61 APRV-01 [x].
- **Reproduction:** Read the cited lines.
- **Impact:** The user (who by the charter has little trading expertise and delegated choices) sees live-execution phases as done, with no testnet rehearsal and no API-key/IP attestation. The one-way acknowledgements the process demanded were given by the AI.
- **Why tests miss it:** -
- **Remediation:** Re-open 08-02/09-04 in ROADMAP and REQUIREMENTS, and put the human checkpoints before any live-enable work. Have the user re-confirm the ACK-ONE-WAY and the 10-05 decision.

### F-125 — The paper WS adapter calls the async SDK method `kline_candlestick_streams(...)` without `await`

- **ID:** F-125
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DEFECT
- **Category:** SUMMARY claim false (PAPER-01)
- **Component:** src/adapters/paper_ws.py
- **File:** `src/adapters/paper_ws.py`
- **Lines:** 155-211
- **Invariant:** -
- **Phase/commit:** 07 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 07-04 SUMMARY 'WS BLOCKED' gap. NEW: root cause identified; supervisor drops results; fill simulation missing.
- **Summary:** The paper WS adapter calls the async SDK method `kline_candlestick_streams(...)` without `await`. The handle is therefore a coroutine, `subscribe` then hits its own 'no on_message' RuntimeError, and the paper soak (PAPER-01/03, the 3-6 month long pole) cannot start. 07-01-SUMMARY claims the adapter wraps the official WS surface. Separately, `PaperSupervisor.on_disconnect` discards the backfill/gap results of the resync, and the paper loop has no simulated-fill producer (PAPER-02).
- **Evidence:** Lane verified paper_ws.py:155-166 and the SDK signature; the helper verified the supervisor and loop lines.
- **Expected:** PAPER-01 'ingests WS market data with warm-up/reconnect/resync ... journals gaps'; PAPER-02 attribution with order/fill timestamps.
- **Actual:** paper_ws.py:159-163 `handle = self._ws.kline_candlestick_streams(symbol=..., interval=..., id=...)` (no await); installed SDK websocket_streams.py:430 `async def kline_candlestick_streams`; supervisor.py:169-194 drops `_resubscribe_and_backfill` results (helper); loop.py:535-536 'no simulated fill yet; Phase 7 plan 07-02 adds the simulated-fill path' (never added).
- **Reproduction:** Read the cited lines.
- **Impact:** The schedule long pole (3-6 months of forward evidence) has not started and cannot start. Every day of delay pushes the earliest defensible live date.
- **Why tests miss it:** WS tests use a synchronous fake SDK.
- **Remediation:** Await the SDK call (and create_connection), add a contract test against the real async signature, and journal the resync gaps. Implement the simulated-fill path.

### F-127 — Several safety claims in phases 8-9 are stronger than the code

- **ID:** F-127
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** OPS-01 / Phase 8-9 safety claims overstated
- **Component:** src/reconcile/safe_mode.py, src/ops/drills.py, src/execution/gates.py, src/adapters/telegram_callbacks.py
- **File:** `src/reconcile/safe_mode.py`
- **Lines:** 150-160
- **Invariant:** -
- **Phase/commit:** 08, 09 / 63ca176
- **Known-prior:** PARTIAL KNOWN: v0.3 W1 (SAFE_MODE typed Any). NEW: restart loss, token/version tautology, drill self-fulfilment, revalidation overclaim.
- **Summary:** Several safety claims in phases 8-9 are stronger than the code. (a) SAFE_MODE is in-memory: `SafeModeController.__init__` sets `_in_safe_mode=False` and never rehydrates from the journal, so a restart clears SAFE_MODE. (b) The '8 RUNBOOK drills rehearsed and logged' (OPS-01 [x]) run against fakes; four of them call enter_safe_mode themselves, and the 'drill log' is a test fixture. (c) 'exchangeInfo revalidation at placement' (09-03, SC2) only checks that a caller-supplied snapshot is positive and within TTL; there is no exchange_info call. (d) The 'one-time token' is not carried in the callback: the receiver fetches raw_token from the server-side resolver and passes the same binding values as both the callback and the approval side, so the token and version gates compare server data with itself.
- **Evidence:** Lane verified safe_mode.py:155-158, gates.py:165-185, telegram_callbacks.py:366-437,672-680; drill lines from the helper.
- **Expected:** ROADMAP P8-SC2/SC5, P9-SC2; OPS-01; TELEGRAM §3; SECURITY §8 restart (resume only when consistent).
- **Actual:** safe_mode.py:157 `self._in_safe_mode: bool = False`; drills.py:491,674,716,759 (helper); gates.py:169-184 positivity check only; telegram_callbacks.py:674-677 `raw_token = binding.get("raw_token", "")`, :366-372 vs :430-435 both from binding_context.
- **Reproduction:** Read the cited lines.
- **Impact:** Protections can be lost across restarts. Approval authenticity rests only on the chat-id gate. OPS-01 is checked [x] with no real rehearsal.
- **Why tests miss it:** Tests construct fresh controllers and pass tokens directly into resolve_callback.
- **Remediation:** Persist SAFE_MODE and rehydrate it on start. Carry a single-use nonce in callback_data and verify it against a stored hash. Re-run drills against the real composed process. Fetch exchangeInfo at placement. Uncheck OPS-01/APRV-02 until then.

### F-128 — OPS-02 has no implementation beyond static secret-posture tests

- **ID:** F-128
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** OPS-02 / credentials
- **Component:** src/adapters/binance_usdm.py, src/ops/health.py
- **File:** `src/adapters/binance_usdm.py`
- **Lines:** 526-530
- **Invariant:** -
- **Phase/commit:** 09 / 63ca176
- **Known-prior:** PARTIAL KNOWN: ROADMAP Phase 12 (equity/daily PnL from Binance). NEW: credential loader and permission check absent; OPS-02 status.
- **Summary:** OPS-02 has no implementation beyond static secret-posture tests. Nothing loads API credentials or configures testnet vs live (the adapter builds a default unauthenticated client). No code verifies key restrictions (no-withdrawal, IP allowlist), and the 09-04 operator attestation is still pending. DAILY_STOP's daily loss and sizing equity are caller-supplied, which contradicts P9-SC2 'DAILY_STOP enforced against live state' (equity part is KNOWN, Phase 12).
- **Evidence:** helper report; the lane checked grep apiRestrictions (none).
- **Expected:** OPS-02; SECURITY §1 (separate paper/test and live credentials); P9-SC2/SC3.
- **Actual:** binance_usdm.py:526-527 `def __init__(self, sdk_client=None)` default client; grep apiRestrictions|withdraw|ipRestrict src tests -> none; manager.py:418,439 daily_loss_quote from risk_kwargs.
- **Reproduction:** Read the cited lines.
- **Impact:** The live path cannot actually authenticate, and when wired, key safety is purely by attestation.
- **Why tests miss it:** -
- **Remediation:** Add a credential/config loader (testnet/live separated) and a startup check of GET /sapi/v1/account/apiRestrictions (enableWithdrawals false, ipRestrict true) that fails closed.

### F-110 — GLOSSARY §9 breaks its own 'no synonyms' rule: the Phase-5 codes duplicate older ones (DAILY_STOP/DAILY_STOP_BLOCK, CORRELATED_RISK_LIMIT/CL

- **ID:** F-110
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** canonical enums (D016)
- **Component:** docs/GLOSSARY.md, src/domain/enums.py, src/execution/*
- **File:** `docs/GLOSSARY.md`
- **Lines:** 150-179
- **Invariant:** -
- **Phase/commit:** 03, 05, 08, 09 / 63ca176
- **Known-prior:** NEW.
- **Summary:** GLOSSARY §9 breaks its own 'no synonyms' rule: the Phase-5 codes duplicate older ones (DAILY_STOP/DAILY_STOP_BLOCK, CORRELATED_RISK_LIMIT/CLUSTER_CAP_REJECT, MIN_NOTIONAL_REJECT/NOTIONAL_REJECT, RISK_LIMIT/AGGREGATE_CAP_REJECT, QUANTIZATION_REJECT/UTILIZATION_REJECT). The code also emits reason codes that are not in the GLOSSARY (DISABLED, ENTRY_WITHOUT_PROTECTIVE, NO_FILL, HEALTH_CHECK_FAILED, EXPIRED in paper/journal) and defines an ApprovalResult enum (PENDING/APPROVED/SKIPPED/EXPIRED) that the GLOSSARY does not have, in which SKIPPED merges SKIP_USER and SKIP_BUSY.
- **Evidence:** as above
- **Expected:** D016 'GLOSSARY.md is the only source of truth for statuses/rejection reasons'; GLOSSARY.md:179 'Do not create synonyms'.
- **Actual:** GLOSSARY.md:152-177; enablement.py:27 `_DISABLED = "DISABLED"`; manager.py:671,917 'ENTRY_WITHOUT_PROTECTIVE','NO_FILL'; ops/health.py:611 'HEALTH_CHECK_FAILED'; paper/journal.py:357 'EXPIRED'; enums probe (tmp/requirements_docs_plan/enum_probe.py): ApprovalResult not in GLOSSARY; 09-CONTEXT: 'ApprovalResult value set … carried forward as locked … planner must not relitigate it'.
- **Reproduction:** Read the cited lines.
- **Impact:** The NO_TRADE-by-reason and opportunity analytics (GOV-01/JRN-01) can split one cause across two codes. SKIP_USER vs SKIP_BUSY (needed for the availability analysis) is lost at the approval-result level.
- **Why tests miss it:** Enum tests check code vs its own list.
- **Remediation:** Add a DECISIONS entry that maps legacy codes to fine-grained codes (or deprecates them). Register the ad-hoc codes and ApprovalResult in the GLOSSARY, keeping SKIP_USER and SKIP_BUSY distinct.

### F-114 — The planning status artifacts contradict each other and the repo

- **ID:** F-114
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** planning bookkeeping
- **Component:** .planning/ROADMAP.md, REQUIREMENTS.md, STATE.md, PROJECT.md
- **File:** `.planning/ROADMAP.md`
- **Lines:** 436-455
- **Invariant:** -
- **Phase/commit:** all / 63ca176
- **Known-prior:** PARTIAL KNOWN: v0.3 audit tech_debt 'REQUIREMENTS.md traceability 25/30 Pending'. NEW: ROADMAP table/checkbox/STATE/PROJECT contradictions.
- **Summary:** The planning status artifacts contradict each other and the repo. ROADMAP's progress table shows Phase 1 and Phase 2 as 'Not started 0/TBD', while both are verified and Phase 1 is checked [x]. Phase 2's plan checkboxes are all unchecked. Phase 6's header says '2/3 plans executed' but the table says 3/3 Complete. Plan 08-05 is unchecked in the wave list while Phase 8 is '5/5 Complete'. STATE.md says total_phases 11 while ROADMAP has 17. PROJECT.md still says 'Greenfield code: no src/' and 'Validated: None'. REQUIREMENTS.md has 25/30 'Pending'.
- **Evidence:** as above
- **Expected:** Single consistent status across REQUIREMENTS/ROADMAP/STATE/PROJECT (GSD evolution rules, PROJECT.md:74-89).
- **Actual:** ROADMAP.md:438-439 (Phase 1/2 'Not started'), :93-99 (02-01..02-05 '[ ]'), :193 ('2/3 plans executed'), :283 ('- [ ] 08-05'); STATE.md:13-14; PROJECT.md:15,46,92 ('Last updated: 2026-09-19 after initialization'); REQUIREMENTS.md:108-139.
- **Reproduction:** Read the cited lines.
- **Impact:** Humans and agents reading status get conflicting answers. The REQUIREMENTS checkboxes [x] for APRV-01/02, OPS-01, JRN-01, GOV-01 claim completion that no VERIFICATION supports.
- **Why tests miss it:** -
- **Remediation:** Regenerate the status views from one source (SUMMARY/VERIFICATION frontmatter). Uncheck requirement boxes that have no passing VERIFICATION.

### F-117 — The AGENTS stack drifts from the build

- **ID:** F-117
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** stack / quality gates
- **Component:** pyproject.toml, AGENTS.md, .github/workflows
- **File:** `pyproject.toml`
- **Lines:** 9-41
- **Invariant:** -
- **Phase/commit:** 02 / 63ca176
- **Known-prior:** PARTIAL KNOWN: v0.3 tech_debt '5 pre-existing mypy errors'.
- **Summary:** The AGENTS stack drifts from the build. FastAPI/uvicorn (for /healthz and webhooks), NumPy/SciPy and VectorBT are not dependencies, and there is no HTTP health endpoint (health checks are library functions). AGENTS says 'CI quality gates are the enforcement point', but no workflow runs pytest, ruff or mypy, and HEAD is red on all three linters (ruff 36 errors, 98 files unformatted, mypy strict 5 errors).
- **Evidence:** as above
- **Expected:** AGENTS.md Tech stack table and Development Tools ('CI quality gates are the enforcement point'); TESTING_STRATEGY §12.
- **Actual:** pyproject.toml:9-41 deps; .github/workflows has only paper_freeze_check/registry-gate/research-gate; tool-output/ruff-check.txt 'Found 36 errors', ruff-format.txt '98 files would be reformatted', mypy-src.txt 'Found 5 errors in 4 files'.
- **Reproduction:** Read the cited lines.
- **Impact:** Low. Type errors in drills/supervisor/telegram_notify/reconcile go unnoticed; docs mislead readers about the health surface.
- **Why tests miss it:** -
- **Remediation:** Add a CI (or local task) running pytest+ruff+mypy, fix the red state, and align AGENTS with the actual stack.

### F-118 — ExperimentRecord lacks fields that the frozen protocol makes mandatory: the NO_TRADE count and reason categories (RESEARCH_PROTOCOL §3 'NO_T

- **ID:** F-118
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** experiment record completeness
- **Component:** src/backtest/experiment.py
- **File:** `src/backtest/experiment.py`
- **Lines:** 90-121
- **Invariant:** -
- **Phase/commit:** 06 / 63ca176
- **Known-prior:** NEW.
- **Summary:** ExperimentRecord lacks fields that the frozen protocol makes mandatory: the NO_TRADE count and reason categories (RESEARCH_PROTOCOL §3 'NO_TRADE as a valid outcome'), the declared intrabar tie-break (§3 'declared in the experiment record'), timeframe, and full parameters/cost assumptions (BACKTEST_SPEC §11). They can only go into the free-text result_summary_json/notes. code_version is an unchecked caller string, not a git revision.
- **Evidence:** as above
- **Expected:** RESEARCH_PROTOCOL.md:153-158,182; BACKTEST_SPEC.md:121-136.
- **Actual:** experiment.py:109-121 fields; assemble() default result_summary_json='{}' (experiment.py:183).
- **Reproduction:** Read the cited lines.
- **Impact:** Records can be 'complete' by the identity check while missing the evidence the protocol requires.
- **Why tests miss it:** -
- **Remediation:** Add typed fields (or a schema for result_summary_json) validated in __post_init__.

### F-122 — `backfill_universe` (the DATA-01 bootstrap) and `refresh_symbol_metadata` (DATA-03) have no caller and no CLI entry point

- **ID:** F-122
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** SUMMARY claim false / orphan code
- **Component:** src/data/backfill.py, src/data/metadata.py
- **File:** `src/data/backfill.py`
- **Lines:** 564-600
- **Invariant:** -
- **Phase/commit:** 02 / 63ca176
- **Known-prior:** PARTIAL KNOWN: 02-VERIFICATION human item 2 (live bootstrap never run). NEW: false test claim, no runner.
- **Summary:** `backfill_universe` (the DATA-01 bootstrap) and `refresh_symbol_metadata` (DATA-03) have no caller and no CLI entry point. 02-03-SUMMARY claims tests import backfill_universe, but tests/test_backfill.py does not, and the function has zero tests. DATA-03 'position modes' is not captured in the metadata blob.
- **Evidence:** helper report; the lane confirmed the entry-point list via grep __main__.
- **Expected:** DATA-01 'User can bootstrap 1m/1H/4H candles per symbol'; DATA-03 metadata incl. position modes.
- **Actual:** 02-03-SUMMARY.md:104-107 claim; tests/test_backfill.py:31-36 imports; no __main__ in backfill.py/metadata.py (entry points: analytics.cli, data.collector, data.coverage, ops.backup, paper.freeze); binance_usdm.py:1522-1540 blob fields.
- **Reproduction:** Read the cited lines.
- **Impact:** The user has no supported command to bootstrap candles, which, together with v0.3 M4, leaves the research pipeline without real data.
- **Why tests miss it:** Untested function.
- **Remediation:** Add a CLI for the universe bootstrap and metadata refresh with tests. Record position mode per account, not per symbol.

### F-123 — The report's regime slice reads `trade["regime"]`, which the simulator never emits, so every real backtest shows regime = UNKNOWN

- **ID:** F-123
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** GAP
- **Category:** BKTS-03 regime slice
- **Component:** src/backtest/report.py
- **File:** `src/backtest/report.py`
- **Lines:** 612-620
- **Invariant:** -
- **Phase/commit:** 06 / 63ca176
- **Known-prior:** NEW.
- **Summary:** The report's regime slice reads `trade["regime"]`, which the simulator never emits, so every real backtest shows regime = UNKNOWN. Only the hand-made fixture carries a regime. No parameter-sweep producer exists for the plateau analysis. BKTS-03 is 'Complete' in the 06-03 SUMMARY.
- **Evidence:** as above
- **Expected:** BKTS-03 slices by symbol/period/regime/version; parameter-plateau analysis.
- **Actual:** report.py:619 `by_regime[_safe_str(trade.get("regime"), "UNKNOWN")]`; grep regime src/backtest/simulator.py -> no emission; TradeRecord fields (simulator.py:128-150) have no regime.
- **Reproduction:** Read the cited lines.
- **Impact:** Regime robustness (an acceptance gate: 'not confined to one regime') cannot be evaluated.
- **Why tests miss it:** Report tests use a hand-made trade list with regime.
- **Remediation:** Carry the signal regime into TradeRecord; add a sweep runner or drop the plateau claim.

### F-119 — A blank line at DECISIONS.md:22 splits the decision table, so D018–D030 render as a headerless second table

- **ID:** F-119
- **Severity:** INFO
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** doc hygiene
- **Component:** docs/DECISIONS.md, docs/trading/SIGNAL_AND_ALERTS.md
- **File:** `docs/DECISIONS.md`
- **Lines:** 21-23
- **Invariant:** -
- **Phase/commit:** 01 / 63ca176
- **Known-prior:** NEW.
- **Summary:** A blank line at DECISIONS.md:22 splits the decision table, so D018–D030 render as a headerless second table. The SIGNAL_AND_ALERTS §5 example alert shows 'Expected R:R: 1.8 / 3.9' (below minimum_rr=2.0, so the planner would reject it) and 'Valid until: 16:00 UTC' (presentation zone is Asia/Ho_Chi_Minh per D025).
- **Evidence:** as above
- **Expected:** Internally consistent canonical docs.
- **Actual:** DECISIONS.md:21-23; SIGNAL_AND_ALERTS.md:95,97; params baseline-v3 minimum_rr = 2.0.
- **Reproduction:** Read the cited lines.
- **Impact:** Cosmetic; can mislead readers.
- **Why tests miss it:** -
- **Remediation:** Remove the blank line; fix the example.

## Open Questions

1. **For the L-backtest code lane and B1:** F-120 (same-bar entry/exit lookahead) is also a planning question. Were 06-01's golden fixtures deliberately built with the 1m map keyed on the signal bar? Separately, the 06-01 SUMMARY "Deviations 2-3" (fixtures edited so invalidation passes) should be reviewed. Any backtest evidence produced so far should be treated as void.
2. **For the Binance/exchange lane (A2):** F-126 depends on Binance clientOrderId uniqueness being scoped to open orders. Please confirm this against current docs. In one-way mode, TP2 and the entry-time SL are `closePosition=true` legs, so a second plan on the same symbol shares one net position (see also 09-REVIEW WR-07). Should max_open_positions count per symbol?
3. **For B2 (planning 07-17):** The kill-gate clock started on 2026-09-19. Meanwhile no family can yet produce valid evidence: F-120 (lookahead), v0.3 M4 (no real data path), F-125 (paper WS broken) and F-107 (no data collected). Should the six-month budget be restarted once a valid research pipeline exists? This is a methodology question, not a code one.
4. **For B1:** Is moving Family B's stop so the RR gate can pass (F-113) a legitimate design decision or post-hoc tuning? It has no DECISIONS entry.
5. **Helper-reported items not independently verified by the lane:**
   - The Dockerfile HEALTHCHECK import failure (F-107) is reasoned only.
   - 10-REVIEW-DISPOSITION shows CR-01/WR-04..09 as "open" although fix commits exist (894cdfd, 72416d4, ca139ba, 1b12c8e, 30c3992, 0b82c6e). This is bookkeeping only.
   - 09-REVIEW-DISPOSITION marks WR-06 "fixed", but `gates.py:33-41` still has a "KNOWN GAP" comment with a hard-coded 200 (relevant to F-051).
6. **Unresolved scope:** Is the runtime composition layer (v0.3 M1-M3), and now the user-data stream (F-104), inside v0.3 at all? ROADMAP phases 11-17 do not include a "compose live/paper process" phase. Without it, most orphaned requirements can never be verified.
7. **Could not inspect:** CI history (no GitHub remote, no `gh`); a real OneDrive-synced backup path; any production `.env`; the `logs/` artifacts cited by 07-04 (absent).

## Appendix A — Requirements traceability matrix

Status legend:
- IMPLEMENTED+TESTED: the library is present, and tests exercise the substance.
- PARTIAL: some sub-clauses are missing or wrong.
- IMPLEMENTED-UNTESTED: the code exists but has not been proven in operation.
- CLAIMED-BUT-MISSING
- NOT-STARTED

"Prod caller" means that something in src/ or scripts/ other than tests invokes the code path.

| REQ | ROADMAP phase | Plans (SUMMARY `requirements-completed`) | VERIFICATION | REQUIREMENTS.md box | Main code | Main tests | Prod caller | Lane status | Key gaps (finding IDs) |
|---|---|---|---|---|---|---|---|---|---|
| RSCH-01 | 1 | 01-01, 01-04 | human_needed (content passed) | [ ] | docs/research/RESEARCH_PROTOCOL.md; .github/workflows/research-gate.yml | 01-04 negative-test RED/GREEN txt | CI only (never runs) | PARTIAL | Gate never executes and tripwire vacuous (F-101); no runtime freeze check |
| RSCH-02 | 1 | 01-02 | human_needed | [ ] | docs/research/families/*.md | — | n/a (docs) | PARTIAL | Code geometry ≠ sheet Stage baselines; sheets stale "implemented: NO" (F-113) |
| RSCH-03 | 1 | 01-03 | human_needed | [ ] | docs/DECISIONS.md D022–D028 | — | n/a | PARTIAL | Narrowed from PROJECT "Core Docs audit"; TESTING_STRATEGY §8 residue (F-111, F-116); stage A found 39 more |
| DATA-01 | 2 | 02-05 (02-02 untagged) | human_needed | [ ] | src/data/backfill.py:231,564; quality.py; store.py; coverage.py | test_backfill, test_quality_gates, test_coverage, test_tracer_slice | coverage CLI only; no bootstrap runner | PARTIAL | backfill_universe untested, no caller (F-122); live bootstrap never run; M4 |
| DATA-02 | 2 | 02-01, 02-04 | human_needed | [ ] | src/data/collector.py:342-936; docker-compose app | test_collector (SQLite) | Compose command (never deployed) | IMPLEMENTED-UNTESTED | Not deployed; OI not accumulating (F-107) |
| DATA-03 | 2 | 02-01, 02-04 | human_needed | [ ] | src/data/metadata.py; binance_usdm.exchange_info | test_metadata | none (no refresh runner) | PARTIAL | No position-mode capture; no runner (F-122) |
| DATA-04 | 2 | 02-03 (mis-tag), 02-05 | human_needed | [ ] | src/ops/backup.py; scripts/backup-drill.ps1 | test_backup (fake dump) | CLI `python -m src.ops.backup` | PARTIAL | No pg_restore; on-host, unencrypted, unscheduled (F-108, F-121) |
| DOMN-01 | 3 | 03-01, 03-02, 03-04 | human_needed | [ ] | src/domain/*; src/db/models.py; alembic 0002 | test_domain_entities, _enums, _mappers | via paper/journal assemblers (no writer) | PARTIAL | Seven of 12 DATA_MODEL entities; no transition validation (F-111, F-112); live PG never migrated |
| DOMN-02 | 3 | 03-01, 03-03 | human_needed | [ ] | src/domain/registry.py; ids.py; registry-gate.yml | test_registry, test_registry_gate | registry loader used by backtest/paper | PARTIAL | CI gate red at HEAD (F-101); experiment linkage not persisted (F-112); unregistered exec params (F-103) |
| DOMN-03 | 3 | 03-01 (03-05 body) | human_needed | [ ] | tests/fixtures/phase3, phase4; determinism suites | test_no_lookahead, test_prefix_invariance, test_candle_close_timing, test_domain_boundary | n/a | PARTIAL | Suites cover strategy.evaluate only; simulator lookahead undetected (F-120) |
| STRAT-01 | 4 | none tagged | passed | [ ] | src/core/features.py; strategy.py:79-90,549-581 | test_core_features, test_candle_close_timing | simulator, paper loop | PARTIAL | Forming-bar gate is a heuristic (close_time vs duration); relies on upstream closed-only input |
| STRAT-02 | 4 | none tagged (04-04 body) | passed | [ ] | src/core/strategy.py:491; ids.py:19 | test_core_tracer, test_core_strategy_*, test_prefix_invariance | simulator, paper loop | IMPLEMENTED+TESTED | — |
| STRAT-03 | 4 | none tagged (04-04 body) | passed | [ ] | src/core/planner.py:52-77,266-408 | test_core_planner | simulator, paper loop | IMPLEMENTED+TESTED | Geometry vs family sheets (F-113); TP2 rule unregistered (F-103) |
| RISK-01 | 5 | none tagged | passed | [ ] | src/risk/sizing.py:30-87; quantization.py; gating.py; backtest/costs.py:184-204 | test_risk_sizing, _quantization, _parity | simulator, paper loop, manager | PARTIAL | Fee-unit bug (KNOWN Phase 11); verification wrong (F-109) |
| RISK-02 | 5 | none tagged | passed | [ ] | src/risk/portfolio.py:177-365 | test_risk_portfolio, _parity | simulator, paper, manager | IMPLEMENTED+TESTED (library) | Daily loss/equity caller-supplied (KNOWN Phase 12, F-128); no DAILY_STOP alert (F-106) |
| BKTS-01 | 6 | none tagged | gaps_found (stale) | [ ] | src/backtest/simulator.py | test_backtest_simulator | experiment.assemble only | PARTIAL (unsound) | Same-bar lookahead (F-120); single-exit vs live ladder (F-102); expiry clock CR-04 skipped; slippage units and funding = 0 (06-REVIEW WR-03/WR-13 skipped) |
| BKTS-02 | 6, 07.1 | 06-02 | 07.1 passed | [x] | src/backtest/experiment.py; binding.py | test_backtest_experiment, test_backtest_binding | none (no runner) | PARTIAL | No persistence or runner (F-112); record lacks protocol fields (F-118); range-mr has no 7-key cost set; direct simulator.run bypass (W2) |
| BKTS-03 | 6 | 06-03 | gaps_found (stale) | [ ] | src/backtest/report.py | test_backtest_report (hand-made trades) | none | PARTIAL | Regime slice always UNKNOWN; no plateau producer (F-123) |
| PAPER-01 | 7 | none tagged | missing | [ ] | src/paper/loop.py, supervisor.py, resync.py; adapters/paper_ws.py | test_paper_* | none (M3) | PARTIAL | WS subscribe broken (F-125); gaps logged, not journaled |
| PAPER-02 | 7 | none tagged | missing | [ ] | src/paper/attribution.py, journal.py | test_paper_attribution | none (M3) | PARTIAL | No simulated fills (F-125); no writer |
| PAPER-03 | 7 | 07-04 | missing | [ ] | src/paper/freeze.py; paper_freeze_check.yml | test_paper_freeze | CI cron (never runs) | IMPLEMENTED-UNTESTED | Soak never started; artifact never produced (F-101); watches param hash only |
| APRV-01 | 8 | 08-02 (halted) | missing | [x] | adapters/telegram_notify.py; paper/notify.py; telegram_callbacks.py | test_approval_message, test_paper_notify | none | PARTIAL | LIVE-TAP gate not done (F-124); no money amounts (KNOWN Phase 16) |
| APRV-02 | 8 | none tagged | missing | [x] | src/approval/tokens.py, binding.py, replay.py | test_approval_replay | none | PARTIAL | Token and version gates tautological at the receiver; in-process replay only (F-127, F-126) |
| EXEC-01 | 9 | 09-02, 09-03 | missing | [ ] | src/execution/manager.py, placement.py, fill_monitor.py; binance_usdm.py:1010-1256 | test_execution_* | none (M2) | PARTIAL | No fill source/user-data (F-104); credentials (F-128); WR-07 (F-115); TP ladder parity (F-102) |
| EXEC-02 | 8 | none tagged | missing | [ ] | src/reconcile/compare.py, sweeper.py, safe_mode.py | test_reconcile, test_drills | none (not scheduled) | PARTIAL | No ALGO_UPDATE parsing (F-104); SAFE_MODE lost on restart (F-127) |
| EXEC-03 | 8 | none tagged | missing | [ ] | src/execution/order_ids.py; manager.py:162-204 | test_order_ids, test_execution_manager | none | PARTIAL | Approval consumption missing; duplicate after fill/cancel (F-126) |
| OPS-01 | 8 | none tagged | missing | [x] | src/reconcile/safe_mode.py; src/ops/drills.py | test_drills | none | PARTIAL | Drills on fakes and self-triggered; no alerts (F-127, F-106) |
| OPS-02 | 9 | 09-03 | missing | [ ] | src/ops/health.py; execution/enablement.py | test_execution_health, _enablement, _secret_posture | none | PARTIAL | No credential loader or permission check; attestation pending (F-128, F-124) |
| JRN-01 | 10 | 10-01/03/04/06/09/11/12 | missing | [x] | src/analytics/*; adapters/analytics_files.py, analytics_store.py | test_analytics_* | yes: `python -m src.analytics.cli` | IMPLEMENTED+TESTED (offline) | Inputs have no producer (M3, F-112); live R INCOMPLETE |
| GOV-01 | 10 | 10-02/04/05/09/11/12 | missing | [x] | src/analytics/killgate.py, family.py; enablement.py:199-208 | test_kill_gate_* | CLI yes; enable() link no (M1) | PARTIAL | WITHIN_BUDGET permits live enable (F-105); decisions file empty |

Summary:
- 30 requirements in total.
- IMPLEMENTED+TESTED: 5. Of these, STRAT-02, STRAT-03 and RISK-02 are library-level only, and JRN-01 is offline only.
- IMPLEMENTED-UNTESTED (operationally): 2 (DATA-02, PAPER-03).
- PARTIAL: 23.
- CLAIMED-BUT-MISSING and NOT-STARTED: 0 at requirement level. Several sub-claims are claimed but missing: F-104, F-121, F-126, F-127.
- The v0.3 audit's "12 orphaned" is confirmed: no VERIFICATION exists for phases 07-10. Going beyond it, the lane also downgrades DATA-01..04, DOMN-02/03, STRAT-01, RISK-01, BKTS-02 and RSCH-01..03, which v0.3 counted as satisfied.

### A.1 Lost requirements (doc MUSTs with no REQ-ID)

| Source | Requirement | Code | Finding |
|---|---|---|---|
| AGENTS; EXECUTION_SPEC §1/§6; PRODUCT_SCOPE §4 | User-data stream (orders/fills/ALGO_UPDATE) | absent | F-104 |
| SECURITY §5; RISK §8; EXECUTION_SPEC §6; GLOSSARY §8.1 | Operational/high-priority alerts, DAILY_STOP alert | absent | F-106 |
| DATA_MODEL §5; TESTING_STRATEGY §8 | State-transition validation | absent | F-111 |
| DATA_MODEL §2.2/2.6/2.12; SIGNAL_AND_ALERTS §2 | trades, feature_snapshots, experiment_runs, Signal.regime/feature_snapshot_id | absent | F-112 |
| IMPLEMENTATION_PLAN Phase 2/3 exit gates; D008 | Paper exit gate, smallest capital, passing family before live | not enforced | F-105 |
| SECURITY §1/§8/§9/§10; RISK §6/§7/§12; EXECUTION_SPEC §11 | Encrypted off-host backup, restart sequence, runtime version, SL-widening ban, constraint-snapshot persistence, emergency controls | absent or library-only | F-108, F-116 |
| SECURITY §1 | Credential loading, key-permission verification | absent | F-128 |
| RESEARCH_PROTOCOL §3; BACKTEST_SPEC §11 | NO_TRADE counts, tie-break, params/costs in experiment record | free text only | F-118 |
| CONFIGURATION §1/§4 | All plan-affecting params registered | TP1 fraction, TP2 multiple, TIF unregistered | F-103 |
| RISK §9 / §2 (leverage/margin) | Read leverage/margin before placement | absent | KNOWN ROADMAP Phase 13/14 |

### A.2 Code with no documented rationale (NO-REQUIREMENT)

- `src/core/planner.py:395-400`: TP2 = entry ± 2·(TP1−entry). The only rationale is 04-REVIEW-FIX CR-03 (F-103, F-113).
- `src/core/planner.py:117-131`: the Family B stop was moved under the retest edge, with no DECISIONS entry (F-113).
- `src/backtest/simulator.py:120-126`: the single-exit simplification, justified only by an incorrect "conservative" claim (F-102).
- The `params/*/baseline-v3.toml` value `partial_fill_fraction = 0.5` was chosen "to dodge the whole-number-trap" (hash normalization), not for a market reason. KNOWN F-006.
- `src/execution/manager.py:515`: GTC time-in-force (F-103; see F-005/F-055).
- `ApprovalResult` enum (PENDING/APPROVED/SKIPPED/EXPIRED): a Phase-3 planner assumption, "locked" by 09-CONTEXT and never added to the GLOSSARY (F-110).

### A.3 ROADMAP success criteria vs VERIFICATION

| Phase | SC | VERIFICATION says | Lane verdict |
|---|---|---|---|
| 1 | SC4 parameter run rejected by gate | verified (content) | NOT MET in practice (F-101) |
| 2 | SC2 OI from day one | verified (code) / human_needed | NOT MET operationally (F-107) |
| 2 | SC4 backup+restore drill | verified | PARTIAL: no restore (F-121) |
| 3 | SC3 unregistered semantic changes rejected in CI | verified | PARTIAL: gate red at HEAD (F-101) |
| 4 | SC1-SC4 | passed | MET for strategy core; geometry vs sheets (F-113) |
| 5 | SC1 sizing incl. costs | passed | NOT MET (fee-unit, F-109) |
| 5 | SC3 parity b/p/l | passed | PARTIAL: only determinism was checked at the time |
| 6 | SC1 intrabar/limit/costs | gaps_found | NOT MET (F-120, F-102) |
| 6 | SC2 reproducible experiments + baselines | partial | PARTIAL (F-112, F-118) |
| 6 | SC3 uncertainty report | gaps_found (G4 since fixed) | PARTIAL (F-123) |
| 7 | SC1 / SC2 / SC3 | none | PARTIAL / PARTIAL / NOT MET (F-125, F-101) |
| 7.1 | goal | passed | MET for trend-pullback and breakout-retest; range-mr cannot assemble |
| 8 | SC1 / SC2 / SC3 / SC4 / SC5 | none | PARTIAL / PARTIAL / MET (library) / PARTIAL (F-126) / PARTIAL (F-127) |
| 9 | SC1 / SC2 / SC3 | none | PARTIAL (F-104) / NOT MET-PARTIAL (F-127, F-128) / NOT MET (F-124, F-128) |
| 10 | SC1 / SC2 | none | PARTIAL / PARTIAL (F-105, M1) |

### A.4 Gray areas left to "Claude's discretion" or deferred that affect money or safety

- **09-CONTEXT discretion:** entry-zone limit-price policy and time-in-force, TP1/TP2 split mechanics, reconciler tick cadence. The outcomes are an unregistered fraction, GTC, and no scheduled reconciler (F-103, F-127).
- **05-CONTEXT discretion:** cluster-membership rule details and daily-state thresholds. The doc-level ambiguity is covered by F-013/F-014.
- **02-CONTEXT discretion:** the scheduler implementation. Outcome: the Compose collector was never deployed (F-107).
- **Checkpoints auto-cleared by the executor:** 02-05 off-host target (F-108), 09-01 ACK-ONE-WAY, 10-05 decision (F-124).
- **Skipped or pending:** 09-REVIEW WR-07 and CR-04; 06-REVIEW CR-04, WR-03 and WR-13; 10-REVIEW WR-01, WR-06, WR-10, WR-12 and WR-13 (F-115). 09 deferred-items.md holds only a ruff F401 note, with no money impact.
