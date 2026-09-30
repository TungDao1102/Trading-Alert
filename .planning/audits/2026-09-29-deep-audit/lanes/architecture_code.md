# Lane L2: architecture_code

## Scope

This lane covers stage C (code) at snapshot commit 63ca176. It checks:

- structure against the layering rules
- what can actually be run: entry points and a composition root
- where backtest, paper and live disagree
- typed seams, error-handling style and the Decimal/float boundary
- how config and params are loaded, and which values are hard-coded

Inputs: LANE_BRIEF, AUDIT_CHARTER §11, LANES (L2 and the Stage C note), the A1 "Corrected Rules for Code Audit", the A2 "Exchange Facts for Code Audit", the finding lists from B1, B2 and L1, and `.planning/v0.3-MILESTONE-AUDIT.md` (M1–M4, W1, W2).

Method:

1. `codegraph explore` (cwd = original repo, read-only).
2. An AST import-graph probe and a zero-caller probe: `tmp/architecture_code/imports.py`, `tmp/architecture_code/zerocallers.py`, with output files `imports.json` and `rev.json`.
3. A mypy structural-protocol probe: `tmp/architecture_code/proto/probe_protocols.py`.
4. Targeted reads of the snapshot.

No file was written outside `AUDIT\lanes` and `AUDIT\tmp\architecture_code`.

## Coverage

| file | level | note |
|---|---|---|
| src/** (all 105 .py) | METADATA_ONLY | AST import graph plus a top-level public-symbol reference count |
| src/execution/manager.py | DEEP_READ | L1–595, protective-leg path, `_place_entry_no_blind_retry`, `_check_approval_authorizes_plan` |
| src/execution/placement.py | NORMAL_READ | price rounding, `quantize_protective_qty`, `build_sl_leg` |
| src/execution/enablement.py | NORMAL_READ | controller state |
| src/adapters/binance_usdm.py | DEEP_READ | L426–446 wire conversion, L843–1256 probes, placement, position mode; method list |
| src/adapters/telegram_callbacks.py | NORMAL_READ | `build_application`, dispatch deps, exports |
| src/adapters/telegram_notify.py | NORMAL_READ | `format_approve` |
| src/adapters/analytics_store.py | NORMAL_READ | imports and readers |
| src/risk/gating.py, sizing.py, quantization.py | DEEP_READ | the whole sizing chain |
| src/core/planner.py | NORMAL_READ | L262–290, L436–480 (plan quantity fields) |
| src/backtest/simulator.py | NORMAL_READ | L280–330 parsers, L760–870 pipeline |
| src/paper/loop.py | NORMAL_READ | L60–135 parsers, L440–556 pipeline |
| src/paper/supervisor.py, journal.py | NORMAL_READ | imports, fill inputs |
| src/reconcile/safe_mode.py, sweeper.py | NORMAL_READ | method inventory, init state |
| src/ops/health.py, drills.py | METADATA_ONLY | function inventory, callers |
| src/analytics/live_outcomes.py | NORMAL_READ | L225–260 (R denominator) |
| src/analytics/cli.py | NORMAL_READ | imports, DB read/record |
| src/domain/registry.py | NORMAL_READ | loader and I/O |
| src/domain/trade_plan.py | NORMAL_READ | field list |
| src/data/collector.py | NORMAL_READ | imports, main/healthcheck, universe |
| src/db/models.py, mappers.py | METADATA_ONLY | tables, mapper callers |
| Dockerfile, docker-compose.yml, pyproject.toml | NORMAL_READ | entry points |
| scripts/* | METADATA_ONLY | `__main__` inventory |
| tests/test_execution_manager.py | NORMAL_READ | L700–735 (-2013 test) |
| .venv binance_common/errors.py, utils.py | NORMAL_READ | how the SDK formats errors (read-only) |
| tool-output/mypy-src.txt, pytest.txt | NORMAL_READ | |

## Verified Safe Areas

**Pure-core layering (ARCHITECTURE boundary).** The AST probe covered every `import` and `from` in `src/core`, `src/domain` and `src/risk`. None of them imports polars, duckdb, sqlalchemy, psycopg, fastapi, httpx, telegram, the binance SDK, or asyncio. None imports any `src.*` module outside core/domain/risk. There are two exceptions, both minor:

- `src/domain/registry.py:36` uses pathlib for file reads (see F-209).
- `src/risk/quantization.py:207` imports structlog locally at the call site, as its documented lineage log.

**SDK containment.** The Binance SDK is imported only in `src/adapters/binance_usdm.py` and `src/adapters/paper_ws.py`. python-telegram-bot is imported only in `src/adapters/telegram_*.py`. Non-adapter modules (data/*, paper/*) import only adapter-owned dataclasses such as `Kline`, `FundingTick` and `OiSnapshot`. No SDK model crosses the boundary.

**ORM containment.** `src/db/models` is imported only by db/mappers, alembic env, adapters/analytics_store, data/collector, data/metadata, and analytics/cli (`make_session_factory` and `session_scope` only). The domain model is frozen dataclasses. ORM rows are not domain objects.

**Decimal/float boundary on order paths.**

- `_decimal_to_wire` (`binance_usdm.py:426-446`) rejects non-Decimal and non-finite values and emits `format(value, "f")`.
- The installed SDK `new_order` has no pydantic `validate_call`, so the string passes through unchanged.
- `grep float(` outside `src/analytics` finds only sleep, cadence and jitter timing values. No price, qty, notional or risk value is ever a float.
- The risk functions call `_require_decimal` on every input.

**One risk pipeline.** `src/risk/gating.evaluate_risk` is the single sizing, quantization and portfolio function. It is called by `backtest/simulator.py:807`, `paper/loop.py:508` and `execution/manager.py:418`. Backtest and paper also share `backtest/costs.modeled_costs_per_unit`. Caveats: F-203 (a second, planner-side sizing formula), F-207 and F-208 (live-only price and protective-qty logic).

**Broad `except Exception` (43 sites).** Each one either:

- journals or logs the failure and continues, as in the collector gap rows, the sweeper failure events and the supervisor per-symbol isolation, or
- converts the failure into a fail-closed outcome, as in the manager probes and `paper_ws._to_dict`, which returns None to the extractor that logs it.

The one bare `pass` (`manager.py:578-579`) follows `expire_pending_entry`, which journals its own failure, and runs after SAFE_MODE was already entered.

**Protocol conformance, other seams.** Under `mypy --strict`, the real `BinanceUsdmAdapter` structurally satisfies `reconcile.safe_mode.AdapterLike`, `reconcile.sweeper.AdapterLike` and `paper.supervisor.RestAdapterLike` (probe output). The one mismatch is `ExecutionAdapter` (F-206).

**Enablement default.** `LiveEnablementController.__init__` sets `_disabled=True` (`enablement.py:99-103`). The in-memory state resets toward the safe direction on restart.

## Findings

### F-201 — The only runnable processes are the collector and the offline CLIs. Beyond M1–M4, four more links in the live flow have no production caller.
- **Severity:** MEDIUM · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** composition / runnability
- **Component:** whole `src/` · **File:** multiple (below) · **Invariant:** INV-001 flow (signal→plan→notify→approve→execute→protect→reconcile→journal), INV-076
- **Phase/commit:** 07–10 / 63ca176
- **Known-prior:** KNOWN M1–M4 (v0.3-MILESTONE-AUDIT), F-104 (no user-data stream), F-106 (no alerts), F-122 (backfill/metadata uncalled), F-956 (no composition phase). This finding adds the exact inventory and four more unwired links (M5–M8).

**Evidence (entry-point inventory).** These are the only `__main__` and console entry points:

- `src/data/collector.py:942` (Dockerfile `CMD`, compose `app.command`)
- `src/analytics/cli.py:758`
- `src/data/coverage.py:609`
- `src/ops/backup.py:611`
- `scripts/check_migration_parity.py`, plus fixture generators under `scripts/`

`pyproject.toml` declares no `[project.scripts]`. The only long-running loop in `src` is `collector.py:908 while True`.

**Evidence (additional unwired links, from the zero-caller probe).**

- **M5 — approval request send side.**
  - `approval/tokens.py:19 issue_one_time_token` has 0 callers in src (23 test references).
  - `adapters/telegram_notify.py:211 format_approve` is referenced only by a re-export in `telegram_callbacks.py:55`.
  - `telegram_callbacks.py:712 build_application` has 0 callers.
  - Nothing creates an `Approval` row or sends an APPROVE message with buttons. Only `paper/notify.notify_simulate` sends anything, and it too is unreached (M3).
- **M6 — reconciliation and health scheduling.**
  - `SafeModeController.enter_safe_mode` is called only from `execution/manager.py` (525, 568, 676, 1227) and from `ops/drills.py` (491, 561, 674, 716).
  - `reconcile.compare.compare` is called only from `safe_mode.py:291` (inside `exit_safe_mode`) and from drills.
  - `reconcile/sweeper.py:116 OrphanSweeper` is only re-exported from `src/reconcile/__init__`.
  - All nine `ops/health.py` check functions (292–568) and all `make_*_drill` factories (`ops/drills.py:449-840`) have 0 src callers.
  - So no code path ever detects a divergence and enters SAFE_MODE, and no health verdict is ever computed.
- **M7 — exchange-state feeders for the live path.**
  - `execute_approved_plan` needs `risk_kwargs` (`account_state`, `constraint_snapshot`, `open_positions`, `daily_loss_quote`, `modeled_costs_per_unit`, `parameter_set`) and `gate_kwargs` (`open_algo_count`, `positions_reconciled`).
  - `ConstraintSnapshot(` is constructed only from fixture dicts, at `backtest/simulator.py:303` and `paper/loop.py:106`.
  - `BinanceUsdmAdapter.exchange_info()` (`binance_usdm.py:660`) has no src caller: its only consumer, `data/metadata.refresh_symbol_metadata`, is itself uncalled (F-122).
  - There is no account, balance or commission reader (KNOWN P11/P12). No src code computes `daily_loss_quote` or `open_algo_count` from exchange truth.
- **M8 — live-path persistence.** See F-202.

**Expected:** a composition root, or at least one runnable process per runtime role (live execution, paper soak, reconciler, Telegram bot), wiring the flow end to end.

**Actual:** Only data collection and offline analytics can run. `execution/manager`, `execution/enablement`, `paper/supervisor`, `paper/loop`, `reconcile/*`, `ops/health`, `ops/drills` and `telegram_callbacks.build_application` are reachable only from tests (see `rev.json`).

**Reproduction:** `python -B tmp/architecture_code/imports.py`, then read the "modules with zero src importers" list. Then run `python -B tmp/architecture_code/zerocallers.py`.

**Impact:**
- No live or paper order flow can run.
- Fixing M1–M4 alone would still leave no approval request sender, no reconciler loop and no exchange-derived risk inputs.
- Any quick composition layer would have to invent these inputs, which is exactly where safety rules get lost (see F-203).

**Why tests miss it:** Every module is unit-tested with injected fakes. There is no process-level or smoke test (pytest: 1268 passed, 7 skipped).

**Remediation:** Add a planned composition phase (F-956) with named processes, covering at least:
- an approval sender that mints the token and persists the Approval
- a bot runner
- an execution service that builds `risk_kwargs` only from adapter reads
- a scheduled reconciler tick calling compare → `enter_safe_mode` plus a sweeper and health loop
- a paper-soak runner

Add one end-to-end smoke test per process against fakes.

### F-202 — No operational persistence layer exists. The journal, approval lookup, save and state protocols have no PostgreSQL implementation, and the live analytics reads tables nothing writes.
- **Severity:** MEDIUM · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** architecture / persistence
- **Component:** `src/db`, `src/adapters`, approval, reconcile, execution
- **File:** `src/db/mappers.py` · **Lines:** 47–374 · **Invariant:** INV-087 dedup, INV-075 SAFE_MODE persistence, the JRN-01 journal
- **Phase/commit:** 03/08/09 / 63ca176
- **Known-prior:** Related to F-112 ("never implemented" entities), F-126 (approval consumption), F-127 (SAFE_MODE in memory), F-951 (no local already-sent state), M3. This finding adds the root cause: there is no repository layer at all.

**Evidence:**

- Every `*_to_row` mapper has 0 src callers: `signal_to_row` :47, `trade_plan_to_row` :99, `approval_to_row` :161, `order_to_row` :209, `fill_to_row` :280, `position_to_row` :326, `journal_to_row` :374. They are called only in tests.
- `dispatch_callback` takes `lookup_by_short_id`, `lookup_by_token_hash` and `save_atomic` as bare `Callable` aliases (`telegram_callbacks.py:206-216, 254-256`), and nothing in src implements them.
- Every `JournalLike.record` is a Protocol: `execution/enablement.py:43`, `reconcile/safe_mode.py:79`, `reconcile/sweeper.py:55`, `ops/health.py:90`, `analytics/killgate.py:90`.
- The only concrete `record()` is the in-memory `ops/drills.DrillLog` (`drills.py:225`).
- The only PostgreSQL writers in src are:
  - the collector (`session.merge`, `collector.py:300, 327`)
  - `data/metadata.py:66`, which is uncalled
  - `analytics_store.append_kill_gate_event`
- Meanwhile `adapters/analytics_store.py:38-47` reads signals, plans, approvals, orders, fills, positions and journal rows through the `*_from_row` mappers.

**Expected:** Signals, plans, approvals, orders, fills, positions and journal events are written to PostgreSQL transactionally (AGENTS "Operational Persistence", DATA_MODEL). Approval consumption and dedup, SAFE_MODE and the enablement state are durable.

**Actual:** The schema (alembic 0001–0003) and mappers exist. No write path does.

**Reproduction:** `zerocallers.py` output. `grep -rn "def record(\|session.add\|\.merge(" src`.

**Impact:**
- Every durable-state safety fix (F-126, F-127, F-951, Corrected Rules 10, 25 and 28) depends on a layer that does not exist.
- Live and paper analytics from the DB (the kill-gate and live-outcome reports) would always see empty tables.

**Why tests miss it:** Mapper round-trip tests (`test_domain_mappers*.py`) prove only that the mapping works. The live-PG variants are skipped without `TEST_DATABASE_URL`.

**Remediation:** Add a repository layer: async SQLAlchemy implementations of the JournalLike and approval lookup/save protocols. It needs transactional `save_atomic`, a unique constraint for approval consumption and plan-hash dedup, and persisted SAFE_MODE and enablement rows that are rehydrated at start.

### F-203 — The executed quantity is recomputed at placement from caller-supplied state and never checked against the approved plan. The plan's hashed quantity fields come from a second, cost-free sizing formula.
- **Severity:** MEDIUM · **Confidence:** CONFIRMED (code trace) · **Classification:** DEFECT · **Category:** backtest/paper/live fork, approval immutability
- **Component:** execution/manager, core/planner · **File:** `src/execution/manager.py` · **Lines:** 418–426, 486–487 (planner: `src/core/planner.py:444-448`)
- **Invariant:** INV-049, Corrected Rule 22 (reject-only revalidation; qty and prices immutable), INV-053
- **Phase/commit:** 04/09 / 63ca176
- **Known-prior:** Doc ambiguity F-017 (root cause), approval message without qty F-015/P16, fee-unit bug P11. The code fork itself is new.

**Evidence:**

- The planner computes `risk_budget = _mul(account_state.equity, risk_rate)`, then `suggested_quantity = _div(risk_budget, risk)`, then `quantity_after_rounding = suggested_quantity  # Phase 5 floors; planner passes through` (`planner.py:444-448`).
  - Here `risk` is the bare |entry_ref − SL| distance, with no costs.
  - The value is labelled "after rounding" but is never rounded.
  - These fields are part of the `TradePlan` whose `plan_hash` the approval binds.
- `risk/sizing.py:59-60` computes `risk_per_unit = sl_distance + modeled_costs_per_unit`, so the quantity always differs from the plan's whenever costs are above 0.
- In `manager.py:418`, `verdict = evaluate_risk(**risk_kwargs)` runs with the placement-time `account_state` supplied by the caller.
- `manager.py:487` then sets `quantity: Decimal = sized.quantity`.
- `_check_approval_authorizes_plan` (`manager.py:~210-265`) compares `plan_hash`, `trade_plan_id` and expiry. It never compares `sized.quantity` with `trade_plan.quantity_after_rounding`.

**Expected:** Corrected Rule 22: what the human approved is exactly what is placed. Placement may only re-check and reject. It never re-sizes. The plan carries the final floored quantity from the single risk pipeline.

**Actual:** The order quantity is whatever `evaluate_risk` returns at placement time. It can be larger or smaller than anything that was hashed or shown at approval. The plan's quantity fields are a different, cost-free, unrounded number.

**Reproduction:** Trace `manager.py:418 → 487 → 509-518` (entry_kwargs "quantity"). There is no equality check against `trade_plan.quantity_after_rounding` anywhere in `src/execution`.

**Impact:**
- Approval immutability is broken.
- Journal, analytics and any approval message that uses plan quantities misreport the exposure.
- If equity rises between plan and placement, the order is larger than the approved plan implied. Risk stays within risk_rate × placement equity.

**Why tests miss it:** Manager tests build `risk_kwargs` from the same fixture as the plan, so the two quantities never diverge. No test asserts plan quantity == placed quantity.

**Remediation:**
- Size once, through `evaluate_risk`, at plan creation (after P11 fixes costs), and store the floored quantity and `realized_risk` in the hashed plan.
- At placement, re-run the gates reject-only. Refuse the order if the recomputed quantity differs, or if risk > risk_rate × current equity × 1.05 (Corrected Rule 7).
- Remove or rename the planner's pseudo-rounded fields.

### F-204 — The R-multiple denominator differs between backtest and live evidence (realized_risk after rounding vs the plan's pre-rounding risk_budget)
- **Severity:** MEDIUM · **Confidence:** CONFIRMED (code trace) · **Classification:** DEFECT · **Category:** backtest/live parity (analytics)
- **Component:** backtest/simulator, analytics/live_outcomes · **File:** `src/analytics/live_outcomes.py` · **Lines:** 238–241 (vs `src/backtest/simulator.py:853`, `src/risk/quantization.py:110,143`)
- **Invariant:** INV-098/INV-120 (kill gate and paper exit gate compare like with like), Corrected Rules 31–32
- **Phase/commit:** 06/10 / 63ca176 · **Known-prior:** none found

**Evidence:**

- Backtest: `_patch_record_metadata(..., realized_risk=sized.realized_risk)` (`simulator.py:853`). Here `sized.realized_risk = _mul(rounded, risk_per_unit)` (`quantization.py:110`/accept path), which is the floored quantity × risk per unit including costs.
- Live: `realized_risk: Decimal | None = plan.risk_budget` (`live_outcomes.py:238`). Here `plan.risk_budget = equity × risk_rate` at plan time (`planner.py:444`), before rounding and regardless of the filled quantity.
- Both feed `analytics/stats.r_value(realized_pnl, realized_risk)` (`stats.py:48`).

**Expected:** One R definition across BACKTEST, PAPER and LIVE evidence. R = net PnL ÷ the risk actually taken, which is the floored filled quantity × risk per unit.

**Actual:** Live R = PnL ÷ allowed budget. Because accepted trades use 60–100% of the budget after rounding, and less on partial fills, live |R| is systematically smaller, by up to 40% or more, than backtest R for the same trade.

**Reproduction:** Take a trade with allowed_risk = 10, a rounded quantity giving realized_risk = 7, and PnL = −7. The backtest records R = −1.0. `live_outcomes` records R = −0.7.

**Impact:**
- Backtest-vs-live and paper parity comparisons, the loss-streak and drawdown-in-R figures, and the kill-gate evidence are biased.
- Live losses look smaller in R than backtest losses.

**Why tests miss it:** Each evidence normalizer is tested against its own fixtures. There is no cross-evidence test that feeds the same trade through both.

**Remediation:** Persist the plan's `realized_risk` (from the single risk pipeline, per F-203) and scale it by filled/planned quantity for live and paper. Use the same field in all three normalizers, and add a parity test.

### F-205 — The no-blind-retry probes treat only "-2011/UNKNOWN_ORDER" as "not found". Query-order not-found is -2013, so every definitive entry rejection becomes UNKNOWN and forces SAFE_MODE, and the ABSENT branch cannot be reached. The protective-leg path probes first, so if algo-query not-found is not -2011, every SL placement fails.
- **Severity:** MEDIUM · **Confidence:** PROBABLE · **Classification:** DEFECT · **Category:** adapter/manager seam, error mapping
- **Component:** adapters/binance_usdm, execution/manager · **File:** `src/adapters/binance_usdm.py` · **Lines:** 1203–1219 (query_order), 857–873 (query_algo_order); manager 183–202, 741–752
- **Invariant:** INV-084 (post-fill protection), Corrected Rules 14 and 25, the EXECUTION_SPEC §10 no-blind-recovery rule
- **Phase/commit:** 09 / 63ca176
- **Known-prior:** The adapter comment itself says -2013 is "must be re-verified". The A2 error table lists -2011 = cancel rejected and -2013 = no such order. This is not reported as a finding elsewhere.

**Evidence:**

- `binance_usdm.py:1212`: `if "UNKNOWN_ORDER" in str(exc) or "-2011" in str(exc): return OrderProbe(found=False...)`, else `raise`.
- The SDK raises `BadRequestError(error_message=msg, status_code=code)`, and its `str()` is `"(code, 'msg')"` (`binance_common/utils.py:473-475`, `errors.py:135-145`). So a query-order not-found shows `-2013`, which does not match.
- `manager.py:183-196`: any `place_entry` exception, including a definitive -2019, -4164 or -1111 rejection, is treated as ambiguous, and the next step is a probe. `except Exception: return _ENTRY_STATE_UNKNOWN`. The caller then calls `enter_safe_mode(reason=ENTRY_STATE_UNKNOWN)` (`manager.py:525`).
- `tests/test_execution_manager.py:715` uses `RuntimeError("-2013 Order does not exist")` as the "probe raises" case and asserts SAFE_MODE. The design intends this, but it means the real not-found answer is always treated as unknown.
- Every protective leg runs `query_algo_order_by_client` first (`manager.py:741-752`). Any exception is marked "probe" and the leg is unconfirmed. The execute path then enters SAFE_MODE with ENTRY_WITHOUT_PROTECTIVE and cancels the entry (`manager.py:560-580`). The algo-query not-found code (-2011 is assumed at `binance_usdm.py:863-866`) is not verified in the A2 facts.

**Expected:** Classify exchange errors:
- definitive request rejections (4xx with a known code) → NO_TRADE, no SAFE_MODE
- the documented not-found code for each endpoint → absent
- only a timeout, 5xx "unknown" or network failure → probe, then UNKNOWN

**Actual:**
- Any rejected entry sends the whole system into SAFE_MODE, which is in memory and has no automatic exit (F-127).
- The `_ENTRY_STATE_ABSENT` branch cannot be reached with the real adapter.
- If algo-query not-found is not -2011, no trade can ever get a confirmed SL, and each approved trade ends in SAFE_MODE plus an entry cancel.

**Reproduction:**
1. Construct `BadRequestError(error_message="Order does not exist.", status_code=-2013)` and pass it through `query_order_by_client`'s except clause. The mapping re-raises.
2. The manager returns ENTRY_STATE_UNKNOWN (see the test at L710-727).

**Impact:** This fails closed, so there is no money loss. But live trading is unavailable, or stuck in SAFE_MODE after every exchange rejection. Operators get trained to clear SAFE_MODE by hand, which weakens it as a safety signal.

**Why tests miss it:** A fake adapter stands in for the exchange. No recorded Binance error fixtures exist for query-not-found or algo-query-not-found.

**Remediation:** Verify the not-found codes for GET `/fapi/v1/order` and GET `/fapi/v1/algoOrder` against the official docs or testnet and record them as fixtures. Map on the `status_code` attribute, not on the string. Add a `DefinitiveReject` classification in the adapter so the manager returns NO_TRADE without SAFE_MODE.

### F-206 — The `ExecutionAdapter` Protocol is `**kwargs: Any`, so the real adapter is not assignable under strict mypy and the entry and leg keyword contract is unchecked statically
- **Severity:** LOW · **Confidence:** CONFIRMED (mypy probe) · **Classification:** DEFECT · **Category:** typed seam
- **Component:** execution/manager · **File:** `src/execution/manager.py` · **Lines:** 69–89 · **Invariant:** AGENTS "mypy strict over execution paths"
- **Phase/commit:** 09 / 63ca176 · **Known-prior:** Extends W1 (enablement and safe_mode typed Any). This finding covers the adapter seam.

**Evidence:**

- Protocol: `async def place_entry(self, **kwargs: Any) -> Any` and `async def place_algo_protective(self, **kwargs: Any) -> Any`.
- The probe `x: ExecutionAdapter = BinanceUsdmAdapter(...)` gives mypy `error: Incompatible types in assignment ... place_entry(self, *, symbol: str, side: str, ...)`. See `tmp/architecture_code/proto/probe_protocols.py`.
- The manager passes a hand-built dict (`manager.py:509-518`, `541-551`). A misspelled key would fail only at runtime.
- The keys match today, and there are no `safe_mode`, `sweeper` or `RestAdapterLike` errors.

**Expected:** Protocol methods whose keyword-only signatures match the adapter, so a composition root type-checks without `cast`.

**Actual:** Any composition root must `cast` or `type: ignore` the real adapter. A future key drift (for example adding `good_till_date` for GTD per Corrected Rule 12) is not caught statically.

**Reproduction:** Run mypy on the probe file (command in the Scope section).

**Impact:** A seam defect found only at runtime would sit on the order-placement path.

**Why tests miss it:** The tests inject `FakeExecutionAdapter`, which accepts `**kwargs`.

**Remediation:** Give the Protocol explicit keyword-only signatures that mirror `BinanceUsdmAdapter`. Add a mypy-checked conformance assignment in a test.

### F-207 — Price-tick rounding exists only on the live path, and runs after sizing. Backtest and paper size and simulate on unrounded zone-mid and SL. Live rounds the SL toward the entry, against Corrected Rule 6.
- **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** DRIFT · **Category:** backtest/paper/live fork
- **Component:** execution/placement, risk/gating, backtest/simulator · **File:** `src/execution/manager.py` · **Lines:** 471–484 (placement.py 126–218; gating.py 69–72, 100–107)
- **Invariant:** Corrected Rule 6 (round prices first, then size; SL away from entry), INV-104 identical semantics
- **Phase/commit:** 09 / 63ca176 · **Known-prior:** F-029 (doc silent). This finding is the code fork.

**Evidence:**

- `evaluate_risk` uses `entry_ref = (entry_min+entry_max)/2`, unrounded, for sizing and for the minNotional reference price (`gating.py:69-72, 100-107`).
- Only the manager then applies `quantize_price(..., direction=entry_limit_rounding)` and `sl_trigger_rounding`. The docstring at `placement.py:204-210` reads: "SL triggers round TOWARD the entry (LONG up, SHORT down)".
- The simulator fills at the unrounded `entry_ref` (`simulator.py:478-517`) and exits at the unrounded `stop_loss_price`.

**Expected:** One tick-rounded price set is computed before sizing and used identically in backtest, paper and live. The SL rounding direction follows the corrected rule and is recorded.

**Actual:** Live uses rounded prices, both of which shrink the stop distance. Sizing and the backtest use unrounded prices. The minNotional check uses a price that differs from the order's limit price by up to one tick.

**Reproduction:** Take a zone mid that is off the tick grid (for example a mid of x.x05 with tick 0.01). The live limit differs from the simulated fill price.

**Impact:**
- The effect per trade is small, at most about 1 tick each.
- Stop-outs are slightly more frequent than in the backtest.
- The realized-risk and utilization gates are evaluated on a geometry that is never placed.

**Why tests miss it:** The parity fixtures use on-grid prices.

**Remediation:** Move price quantization into the shared core (planner or risk), before sizing. Choose and record the SL rounding direction per Corrected Rule 6.

### F-208 — Logic and constants are duplicated across paths: protective-qty quantization re-implemented, fixture parsers copied, the live-5 universe written in four places, the MARK_PRICE literal written twice
- **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** IMPROVEMENT · **Category:** duplication / hard-coded config
- **Component:** multiple · **File:** `src/execution/placement.py` · **Lines:** 221–275 · **Invariant:** INV-104, INV-057, the AGENTS "parameter registry" rule
- **Phase/commit:** 05–09 / 63ca176
- **Known-prior:** F-908 (cluster hard-coded), F-958 (MARK_PRICE), F-056 (MARKET_LOT_SIZE, reduce-only notional), P17 (quote asset). This finding adds the duplication map.

**Evidence:**

- `placement.quantize_protective_qty` says it "Mirrors `src/risk/quantization.py:quantize` gate order". It re-implements the floor, minQty and minNotional logic.
  - It applies MIN_NOTIONAL to reduce-only TP legs, which Binance exempts (A2: `-4164 ... unless reduce only`).
  - It uses LOT_SIZE step and min, while triggered `*_MARKET` legs fall under MARKET_LOT_SIZE (F-056).
- `_coerce_money`, `_parse_utc_aware`, `_parse_candle`, `_parse_account_state`, `_parse_constraint_snapshot` and `_parse_open_positions` exist twice, functionally identical (they differ only in docstrings and formatting), in `backtest/simulator.py:60-325` and `paper/loop.py:60-130`.
- The live-5 literal appears at:
  - `data/backfill.py:549 LIVE_5`
  - `execution/manager.py:51-53 LIVE5_SYMBOLS`
  - `backtest/report.py:34 LIVE5_SYMBOLS`
  - `risk/portfolio.py:30`, a 4-symbol cluster
- `"working_type": "MARK_PRICE"` appears at `manager.py:550` and `placement.py:325, 437, 450`.
- `"time_in_force": "GTC"` appears at `manager.py:515`.
- `QUOTE_ASSET = "USDT"` appears at `analytics/live_outcomes.py:65`.

**Expected:** Each piece of logic exists once in the shared core. Universe, working type, time-in-force and quote asset are registry or config values recorded with the plan.

**Actual:** The copies can drift independently. The TP-leg quantization already differs from the exchange rules.

**Reproduction:** grep the literals as listed.

**Impact:**
- A TP1 leg can be rejected locally (a single-TP fallback or no TP) when Binance would accept it.
- A universe change needs four edits.

**Why tests miss it:** Each copy has its own fixtures.

**Remediation:**
- Reuse `risk.quantization` for protective legs, with a reduce-only flag that skips the notional check and a MARKET_LOT_SIZE-aware constraint snapshot.
- Extract one fixture-parsing module.
- Define the universe, working type, TIF and quote asset once, in registry or config.

### F-209 — Minor layering leaks: `src/domain/registry.py` performs file I/O on a path relative to the source tree, and the image omits `params/`
- **Severity:** INFO · **Confidence:** CONFIRMED · **Classification:** IMPROVEMENT · **Category:** layering / packaging
- **Component:** domain/registry, Dockerfile · **File:** `src/domain/registry.py` · **Lines:** 36, 41, 383–387 · **Invariant:** pure-domain rule (ARCHITECTURE)
- **Phase/commit:** 03 / 63ca176 · **Known-prior:** none

**Evidence:**

- `registry.py:41`: `REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "params"`.
- `registry.py:387`: `path.read_bytes()` inside `src/domain`.
- The Dockerfile copies only `src`, `scripts` and `alembic.ini`, not `params/`.
- `quantization.py:207` imports structlog locally. This is documented and harmless.

**Expected:** The domain holds pure parsing and validation. File loading lives in an adapter or loader with an injectable root. Any image that may run backtest or analytics includes the registry.

**Actual:** Loading is coupled to the checkout layout. In the container, `load_parameter_set` would raise `UnregisteredParameterSet`. That fails closed, and only the collector runs in the image today.

**Reproduction:** Read the lines cited.

**Impact:** Hygiene only.

**Why tests miss it:** Tests run from the checkout.

**Remediation:** Split the loader (I/O) from the parser, with the root injected. `COPY params ./params` if the image is ever used beyond the collector. Pin the `uv` image (`ghcr.io/astral-sh/uv:latest` is unpinned).

## Open Questions

- **For L4/L5 (exchange and execution lanes):** confirm the official not-found error codes for GET `/fapi/v1/order` and GET `/fapi/v1/algoOrder`. F-205's severity depends on the algo case: if it is not -2011, live SL placement never confirms.
- **For L3 (business invariants):** F-203 (re-sizing at placement) overlaps Corrected Rules 7 and 22. L3 may want to pick the placement-time equity tolerance rule.
- **For L6 (analytics/methodology):** F-204's R-denominator fork. Also check whether PAPER evidence uses a third definition. Paper fills have no producer (F-125), so PAPER R currently comes only from caller-supplied dicts.
- The Dockerfile HEALTHCHECK ImportError is already reported (F-107, PROBABLE). This lane did not re-verify it by running Docker.
- The mypy baseline has 5 errors (`tool-output/mypy-src.txt`). They were inspected (variable-reuse typing in `telegram_notify.py:287`, `drills.py:814`, `supervisor.py:298`, `compare.py:517`). None is a behavioral bug on an order path.
