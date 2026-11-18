# Lane X07: prior_findings_closure_b

## Scope

Closure check of the 2026-09-29 deep audit (`.planning/audits/2026-09-29-deep-audit/findings.json`,
snapshot `63ca176`) for the docs / requirements / planning-decision findings: every primary
(non-`duplicate_of`) finding F-0xx, F-1xx, F-9xx of severity HIGH or MEDIUM (61 rows: 6 HIGH, 55
MEDIUM), plus a spot check of 15 of the 22 primary LOW ones. Verdict per old id, judged from the
docs, DECISIONS rows and code of snapshot `55885b9`: FIXED / PARTIAL / OPEN / SUPERSEDED /
WRONGLY_CLOSED. Plans, SUMMARY and VERIFICATION files are used only to locate code, never as
evidence. Finished lane files in `lanes/` were used as leads and re-checked.

## Closure table (written row by row)

| Old id | Old sev | Verdict | Evidence (snapshot) | Note / G-id |
|---|---|---|---|---|
| F-051 | MEDIUM | FIXED | `docs/trading/EXECUTION_SPEC.md:305-307` "200 open conditional orders across all symbols ... track ... account-wide (no symbol filter)"; `src/execution/gates.py:26-42,182` `count + legs >= 200`; live producer `src/live/risk_inputs.py:26-28,592,722` counts ALL open algo orders of the account | tests/test_execution_gates.py headroom tests |
| F-054 | MEDIUM | FIXED | `docs/trading/EXECUTION_SPEC.md:102-121` section 6.1: no margin check before trigger, TRIGGERED/FINISHED = UNKNOWN, "FINISHED alone does not prove that the protective exit executed", REJECTED/EXPIRED at trigger; table pinned to `src/domain/algo_status.py` `ALGO_STATUS_TABLE` by a test (line 116) | - |
| F-010 | MEDIUM | FIXED (priceProtect implicit) | D037; `docs/integration/BINANCE.md:95` workingType MARK_PRICE sent explicitly; `src/adapters/binance_usdm.py:1563-1579` sends `working_type`, never `priceProtect` (exchange default false = guaranteed trigger, the value the old audit recommended); `src/backtest/exits.py:3,99-105` triggers on mark 1m klines. priceProtect is nowhere named as a choice in docs (hygiene only) | - |
| F-958 | MEDIUM | SUPERSEDED (D037) | D037 chose MARK_PRICE and required the backtest to use markPriceKlines; `src/backtest/exits.py:3` "SL and TP triggers are evaluated on mark-price 1m klines (D-10, D037)"; live binding `src/execution/binding.py:225-227` `check_working_type` | - |
| F-009 | MEDIUM | FIXED | D034; `docs/operations/SECURITY_AND_OPERATIONS.md:109-118` "SAFE_MODE blocks new entry orders only ... Protective and reduce-only orders are always allowed"; code: `src/execution/manager.py:600` SAFE_MODE guard only on the entry pipeline; `src/execution/protection.py` and `src/execution/emergency_close.py` only ENTER SAFE_MODE (protection.py:1079,2667,2765; emergency_close.py:943) and never test it before a stop or close | - (section 7 "Implementation status (Phase 20) ... not run by any deployed process yet" is stale since Phase 24: Open Questions) |
| F-952 | MEDIUM | SUPERSEDED (D034, D077, D079) | Cancel-only reconciler replaced by the fill-driven coordinator: `src/execution/protection.py:1-80` (same-id re-place of a never-confirmed stop proved ABSENT, B5 stop-reject -> CLOSE_REQUIRED -> emergency close); WR-07 "emergency close cancels SL before flat" no longer holds: `src/execution/emergency_close.py:1-40` closes reduce-only and only sweeps protectives after two flat reads (protection.py:77-80 "FLAT needs the entry terminal AND REST flat, after which ... swept"); "expired entry leaves close-all SL" is moot because no stop exists before a fill (D079) | - |
| F-953 | MEDIUM | OPEN (owned: ROADMAP Phase 26 SC1) | `src/execution/enablement.py:263-270` still refuses only unevaluated and INSUFFICIENT_EDGE; WITHIN_BUDGET passes. Mitigated: the only caller of `.enable(` in src/scripts is `src/live/enablement.py:253` `enable_demo`, which raises `LiveEnableForbidden` for any mode but DEMO (234-237); no LIVE enable path exists. `.planning/ROADMAP.md:1507` "WITHIN_BUDGET is refused" is a Phase 26 criterion, not code | no G (tracked, unreachable now) |
| F-960 | MEDIUM | PARTIAL | Thresholds frozen numerically before Validation: `docs/research/RESEARCH_PROTOCOL.md:281-289` G1-G5, Holm over 48, "a human may never pass a candidate that fails" (D032/D043/D069). The skipped 10-REVIEW WR-01/06/10/12/13 are still open and parked in ROADMAP Phase 26 SC1 (`.planning/ROADMAP.md:1507`) | no G (tracked) |
| F-022 | HIGH | FIXED within run 1 | `docs/research/RESEARCH_PROTOCOL.md:281-295` numeric G1-G5 incl. block-bootstrap CI and one Holm-Bonferroni over 48 hypotheses, frozen since v1.1.0 (D043) before Validation; residual (no control across a second run, G5 has no significance test) is X09 G-2102 | see G-2102 (X09) |
| F-023 | MEDIUM | PARTIAL (redefined) | Exit gate now defined (D061 item D, `.planning/ROADMAP.md:706,736`): 14-day trial soak, 95 % coverage, freeze CLEAN, zero-tolerance decision parity, "no minimum trade count". It is an engineering-parity gate; the old asks (realized fill rate/slippage/latency inside the model, paper expectancy not below the backtest bound) are absent; PAPER-03 (3-6 months, no tuning) is left to Phase 26. Edge evidence therefore rests only on G1-G5 of the research run, which X09 G-2101 reports no candidate can pass | no G (the redefinition is stated openly; cost calibration moves to Demo/CANARY, Phase 25/26) |
| F-001 | MEDIUM | FIXED | D046; `docs/trading/RISK_MANAGEMENT.md:34-40` `modeled_costs = sizing_entry x (entry_fee_rate + entry_slippage_rate) + stop_price x (exit_fee_rate + exit_slippage_rate)` from the adverse zone edge; code `src/risk/cost_rates.py:122-151` (lead X04 `core_strategy_risk.md:75`, re-read), rate > 1 % refused as a unit error (RISK_MANAGEMENT:55). The generic section 2 pseudo-formula still says `worst_case_distance_to_SL + modeled_costs` but is followed by the unit definition | - |
| F-002 | MEDIUM | FIXED | `docs/trading/RISK_MANAGEMENT.md:56-59` `STOP_TOO_TIGHT` (`min_stop_distance_rate` 0.003) and `COST_TO_RISK_EXCEEDED` (`max_cost_to_risk` 0.15) before quantization; canonical codes `docs/GLOSSARY.md:176,188`; code `src/risk/cost_guards.py:29-62` | - (the 1/3 bps slippage numbers are unmeasured: X09 D046 DOUBTFUL) |
| F-004 | MEDIUM | FIXED | `docs/research/RESEARCH_PROTOCOL.md:142-144` touch vs fill, "A limit fills only on a trade-price trade-through of one tick"; `src/backtest/entry.py:12-15,68-99` `is_trade_through` (`low <= limit - tick`), `is_touch_only` counted; stop exits carry `exit_slippage_rate` (RISK_MANAGEMENT:57, `src/backtest/exits.py:99-105` stop fills at the adverse of trigger and mark-minute open) | - |
| F-902 | HIGH | FIXED | Same code as F-004: fill price is the snapped limit (zone mid) only on a 1-tick trade-through (`src/backtest/entry.py:4,12-15,44-74`); edge touches are `touch_no_fill_count` (`src/backtest/lifecycle.py` advance docstring 476-479) | - |
| F-120 | HIGH | FIXED | D052(a); `src/backtest/engine.py:18-19` "A plan created at close N is active from bar N+1 because `advance` never reads a minute closing at or before the signal close"; `src/backtest/lifecycle.py:3,469-495` window `(start_exclusive, end_inclusive]`; exits walk mark minutes from the entry time forward across bars (lifecycle 483-485) | - |
| F-005 | MEDIUM | FIXED | D036; `docs/trading/RISK_MANAGEMENT.md:52` "The entry fee is modeled at the taker rate (D036)"; live `docs/integration/BINANCE.md:173` per-side `max(parameter rate, account taker rate)`, `src/live/risk_inputs.py:394` `resolve_live_cost_rates` | - |
| F-006 | MEDIUM | FIXED | D038; `docs/trading/RISK_MANAGEMENT.md:52` "Canonical parameter sets use `partial_fill_fraction` 1.0" | - |
| F-021 | MEDIUM | FIXED | D052; `docs/trading/RISK_MANAGEMENT.md:60` and `src/backtest/funding.py:3-13` `funding_pnl = -sign(position) x quantity x markPrice(fundingTime) x fundingRate` at every actual fundingTime, no 8 h grid; convention string hashed into the cost model (`src/backtest/costs.py:9,57`) | - |
| F-905 | MEDIUM | FIXED | Funding modeled: `src/backtest/funding.py` (above) charged by the engine (`src/backtest/engine.py:7-8` "the funding payments of every open position into dated Bookings"); funding history collected under D049 | - |
| F-102 | MEDIUM | FIXED | Backtest now models the live ladder: `src/backtest/exits.py:99-130` stop leg, TP1 partial, TP2; `src/backtest/exits.py:296-334` sizes TP legs with the live helper `size_protectives_to_filled_qty` | - |
| F-103 | MEDIUM | SUPERSEDED (D052 / D-27) | TP1 fraction is a code constant covered by the simulator semantics version, not a registry key: `src/backtest/semantics.py:32-34` `TP1_QUANTITY_FRACTION = Decimal("0.5")`, used by backtest (`exits.py:319`) and by live wiring (`src/live/risk_inputs.py:708`, `src/live/wiring.py:1204`), one source; entry TIF is GTD (D079), no longer GTC | - |
| F-962 | MEDIUM | FIXED | Exit slippage, adverse-edge distance, taker entry (D036), cost-to-risk ceiling all in RISK_MANAGEMENT 2-3; `max(param, account)` fee rule `docs/integration/BINANCE.md:173`, `src/live/commission.py`, `src/live/risk_inputs.py:394` | - |
| F-018 | MEDIUM | PARTIAL | TP1 qty `filled_qty x fraction` floored to stepSize (`src/execution/placement.py:378-391`); TP legs placed only after the entry is terminal, no continuous resizing (`docs/trading/EXECUTION_SPEC.md:148`); SL is closePosition and stays unchanged after TP1. Not done: a TP1 leg below minQty/minNotional makes the whole TP sizing NO_TRADE (placement.py:385-391) -> live TP_UNAVAILABLE (SAFE_MODE, stop kept, `src/execution/protection.py:107-108`) instead of the recommended single TP; no doc sentence "no breakeven/trailing in V1" | no G (behaviour fails closed; parity of this branch belongs to X02/X03) |
| F-007 | HIGH | FIXED | `src/execution/pre_placement.py:3-6,38-56` pure refusals run before the approval is consumed: VALIDITY_TOO_SHORT, PLAN_INVALIDATED_BEFORE_PLACEMENT (CANDLE_CLOSE rule), MARK_PRICE_CROSSED_STOP / MARK_PRICE_OUTSIDE_ZONE and the same three for LAST price, each with an age bound (`config/execution/execution-limits-v1.toml:52-54` 900 s, 5000 ms, 30000 ms); post-fill stop reject -> B5 close (`src/execution/protection.py:24-27`). The 30 s last-price bound is X09 G-2106 | see G-2106 (X09) |
| F-016 | MEDIUM | FIXED | `min_remaining_validity_seconds = 900` (limits:52, provenance DECISION) checked at placement (`pre_placement.py` VALIDITY_TOO_SHORT); exchange-side backstop GTD with `GTD_MIN_AHEAD_SECONDS = 600` (`pre_placement.py:56-61`), EXECUTION_SPEC 6.3; operator-availability bias is measured by the SHADOW approval-delay journal (Phase 16 SC3/SC5) | - |
| F-959 | MEDIUM | FIXED | Entry is a GTD LIMIT (D079, `docs/trading/EXECUTION_SPEC.md:142`; adapter `src/adapters/binance_usdm.py:1385` passes `time_in_force`); the system does not rely on GTD expiry and uses `entry_terminal_timeout_ms` 900000 (EXECUTION_SPEC:146) | - |
| F-017 | MEDIUM | FIXED (D078) | Side and prices bound through the plan hash; quantity bound outside the hash as `approvals.approved_quantity`, "quantity may be <= approved, never larger" (D078 items 1-7, AGENTS "Plan binding"). Revalidation may lower the quantity, never raise it: a deliberate, risk-reducing variant of the old "immutable" recommendation | - |
| F-011 | MEDIUM | FIXED | D035/D085; `src/execution/margin_guard.py:9,18,323,501-509` ISOLATED and exactly `TARGET_LEVERAGE` 5, multi-asset refused; `liquidation_buffer_bps = 300`, `headroom_bps = 1000`, bracket age 60000 (limits:74-77) | - |
| F-964 | MEDIUM | FIXED | Same as F-011: liquidation beyond the SL by a 300 bps buffer, isolated recorded in D035, leverage cap 5, Multi-Assets check `BLOCKED_MULTI_ASSETS_MODE` | - |
| F-012 | MEDIUM | FIXED | D086; `src/live/risk_inputs.py:20-21` equity = smaller of wallet and margin balance, bounded by `account.max_equity_age_ms` 15000 (limits:71); `docs/trading/RISK_MANAGEMENT.md:218` `equity_used` recorded in the constraint snapshot | - |
| F-013 | MEDIUM | FIXED | D033 (UTC day, realized + commissions + funding, base = equity at UTC day start, sticky state) and D087; producer `src/execution/daily_stop.py`, live `LiveDayRiskService` (`src/live/risk_inputs.py:22-23`), age bound 300000 ms | - |
| F-963 | MEDIUM | FIXED | P12 goal items delivered: D033/D086/D087 (above) and the user-data stream exists (Phase 18, `src/adapters/binance_userdata_events.py`; D091 silence bound 420000 ms) | - |
| F-014 | MEDIUM | PARTIAL (KNOWN:21-DEFERRED) | "Open" now counts reservations RESERVED, PLACED, OPEN (`src/live/risk_inputs.py:24-25`) i.e. approved-not-placed and working entries; cluster membership still hard-coded `src/risk/portfolio.py:29` `{"BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"}`, per side (313); `cluster_cap` = `risk_rate` 0.005 still allows one aligned position; registered as owner item in `.planning/phases/21-*/` DEFERRED line 31 | no G (known; X04 and X13 report the consequences) |
| F-908 | MEDIUM | PARTIAL (KNOWN:21-DEFERRED) | Ledger part fixed (reservations above); cluster list still a code constant without BNB and outside the 12-symbol research universe (X04 `core_strategy_risk.md:105`) | no G (known) |
| F-015 | MEDIUM | FIXED | D041 confirmation card and D-13 money block: `docs/integration/TELEGRAM.md:68-77` quantity, notional, margin with leverage and its source, loss at SL gross/net, profit per TP, equity used with source and time; built once from `src/risk/money_at_stake.py`, refused when it disagrees with the plan. Liquidation price is not shown (guarded instead by the 300 bps check) | - |
| F-026 | MEDIUM | FIXED | Values exist and are non-null: `reconcile.tick_interval_ms = 15000`, `stale_feed.max_mark_price_age_ms = 60000`, `max_user_data_silence_ms = 420000` (limits:56-66); "The live path refuses while any key is NOT_CONFIGURED" (limits:30) except the alert-only keys | - |
| F-024 | MEDIUM | FIXED | D039/D049; `docs/research/universe/research-universe-v1.toml` FROZEN 2024-10-03, top 12 by trailing 30-day quote volume as of the dataset start, `include_delisted = true`, content hash witnessed by `scripts/decision_alignment/universe.py` | - |
| F-907 | MEDIUM | FIXED | Same manifest; the research universe (12 symbols) is separate from the live-5 config | - |
| F-904 | MEDIUM | FIXED | Splits and single-use holdout: `docs/research/RESEARCH_PROTOCOL.md:281-291` (40/40/20, G5 holdout once, data per gate), marker `docs/research/holdout_consumed.json` (empty: holdout unused), `src/research/run.py:9` "The holdout is never simulated here" | - |
| F-906 | MEDIUM | FIXED | `src/data/backfill_cli.py:18,336-347` depth defaults 1m 12 months, 1h/4h 24 months, overridable `depth_months`; CLI calls `backfill_universe` (794) | - |
| F-961 | MEDIUM | FIXED | `src/paper/attribution.py:25-31` since plan 16-35 the SHADOW approval delay is the measured `acted_at_utc - requested_at_utc`; the 30 s constant (60) only for records with no human action | - |
| F-954 | MEDIUM | FIXED | Money-safety phases 11-23 now precede live enablement; live enable is only possible after Phase 26 (`.planning/ROADMAP.md:1500-1507`), and no LIVE enable caller exists (F-953 row) | - |
| F-955 | MEDIUM | FIXED | Every listed item now has code: min remaining validity and GTD (F-016/F-959 rows), reservations incl. working and approved-unplaced (F-014 row), cost-to-risk (F-002), account-wide algo count (F-051), user-data stream (`src/adapters/binance_userdata*.py`, Phase 18), reconcile cadence (F-026) | - |
| F-956 | MEDIUM | PARTIAL | Runtime composition built (SHADOW `src/paper/shadow_runtime.py`, live `src/live/runtime.py`, Demo smoke 21/21 per AGENTS); re-verification of phases 06-25 is parked in ROADMAP Phase 26 SC2 (`.planning/ROADMAP.md:1508`) | no G (tracked) |
| F-109 | MEDIUM | PARTIAL | Substance fixed: RISK-01 sizing now uses the quote-per-unit cost (D046, F-001 row). The process ask (reopen 05-VERIFICATION, dimensional checks in the verification template) is parked in Phase 26 SC2; RISK-01 stays `[x]` | no G |
| F-124 | MEDIUM | PARTIAL | 08-02 and 09-04 are still `[x]` in `.planning/ROADMAP.md:299,344` and Phases 8/9 "Complete" in the progress table (1576-1577); the blocked 09-04 rehearsal was later executed on Demo by Phase 24 (ROADMAP:1290); recorded human decisions for one-way checkpoints are a Phase 26 SC2 item | folded into G-1751 |
| F-101 | MEDIUM | PARTIAL | registry-gate now pins all 73 `params/*/*.toml` (probe: 73 pins in `tests/fixtures/phase4/parameters.json`, 0 missing). research-gate identity and tripwire checks are still vacuous: they look for files named `experiment*.json`/`backtest*.json` with camelCase keys (`.github/workflows/research-gate.yml:81-99`), while the 480 committed records are `docs/research/experiments/research-run-1*/<sha256>.json` with snake_case keys, and the tripwire scans JSON/YAML while parameter sets are TOML; `docs/DOC_STATUS.md:13,53` still calls it the "executable gate" with "three fail-closed checks". Identity is in fact enforced by the record type (`src/backtest/experiment.py:106-116,253-258`). Real remote CI is a Phase 26 SC4 item | G-1750 |
| F-104 | HIGH | FIXED | User-data stream exists: `src/adapters/binance_userdata.py`, `binance_userdata_events.py` (ORDER_TRADE_UPDATE and ALGO_UPDATE incl. `o.pP`, 1040,1095), `binance_userdata_supervisor.py`, `src/live/stream.py`; started before the first reconcile (D094); fills are also polled by REST each step (D079: the stream is not a confirmation source) | - |
| F-106 | MEDIUM | FIXED | Closed alert contract `ALERT_EVENTS` (`src/ops/alerts.py`, `src/ops/alert_wording.py`), producer table `docs/operations/SECURITY_AND_OPERATIONS.md:68-88` (SAFE_MODE entry, DAILY_STOP, CLOSE_REQUIRED, TP_UNAVAILABLE, TASK_STALLED ...) | - |
| F-107 | MEDIUM | OPEN | DATA-02 still `[x]` (`.planning/REQUIREMENTS.md:19,129`); no evidence in the repo of continuous OI ingestion: `.planning/STATE.md:671` "until it exists the collector runs on a dev machine", `16-37-consistency.md:55` "There is NO `data_class=oi` directory (open interest) locally", D059(4) "the repository cannot enforce the date". OI is not read by `src/core`, so no decision depends on it | G-1751 |
| F-108 | MEDIUM | FIXED (stale docstring) | Off-host encrypted S3 via rclone crypt with manifest + cryptcheck (D062/D064/D066), scheduled `deploy/systemd/trading-backup.timer`, `retain` subcommand, `restore-db` with `pg_restore` (`src/ops/backup.py:27-29,747-821,1007`). Module docstring `src/ops/backup.py:17-24,33-37` still says "the actual pg_restore is left to the operator" and "Off-host target is set via BACKUP_TARGET" (read nowhere) | hygiene, Open Questions |
| F-121 | MEDIUM | OPEN | A real PostgreSQL restore onto a fresh machine has no evidence in the repo (no `pg_restore` in any `.planning/phases/*/evidence`); D064 real-S3 gate "result pending until the owner runs it" (`.planning/STATE.md:637`); DATA-04 still `[x]` (`REQUIREMENTS.md:21,131`); owned by Phase 26 SC3 | G-1751 |
| F-111 | MEDIUM | FIXED | `src/domain/transitions.py` legal-transition tables, `IllegalTransition`; `tests/test_transitions.py` exhaustive cross-product, `tests/test_persistence_transitions_pg.py` DB triggers (TESTING_STRATEGY section 8:121-123). Residual: the section 8 example still uses the pseudo-state `NEW PROTECTIVE ORDER` (line 114) and says the tables are "awaiting user confirmation" while D051 says confirmed 2026-10-02 | hygiene |
| F-112 | MEDIUM | SUPERSEDED (D045) | D045(a) records the exclusion of `trades`, `feature_snapshots`, `experiment_runs` | - |
| F-113 | MEDIUM | SUPERSEDED (D054) | Phase 15 geometry correction recorded in D054 with variant ids; values PLACEHOLDER (X09: CANNOT_JUDGE strategy content) | - |
| F-115 | MEDIUM | PARTIAL | WR-07 moot under D079 (F-952 row); CR-04 replaced by "TP legs are placed after the entry is terminal" (`EXECUTION_SPEC.md:148`); 10-REVIEW WR-01/06/10/12/13 parked in Phase 26 SC1 | no G (tracked) |
| F-116 | MEDIUM | FIXED (mostly) | Never widen a stop: D034 "never wider" (SECURITY section 7); restart sequence: D094 start order, `src/live/startup.py`; constraint snapshot persisted on the write-ahead path (D095); version in health: build-stamped revision (D106); emergency close command `/close SYMBOL` (D104). Not checked here: application-level secret encryption (SECURITY_AND_OPERATIONS:8 keeps host disk encryption only) | - |
| F-125 | MEDIUM | FIXED | `src/adapters/paper_ws.py:307,377,474` both SDK coroutines are awaited | - |
| F-126 | HIGH | FIXED | Exactly-once entry by a durable intent row keyed per approval (D051, D080); `tests/test_execution_exactly_once_pg.py` (TESTING_STRATEGY:156) covers FILLED/CANCELED first entry, restart and a two-thread race, with negative controls (PG test, skipped in this audit's run) | - |
| F-127 | MEDIUM | FIXED | (a) SAFE_MODE rehydrated: `src/reconcile/safe_mode.py:313-353,372-411` (`rehydrate`, restart never reads SAFE_MODE as off; X12 Verified); (b) drills now run in the composed process on Demo (Phase 24 smoke); (c) one-time token in callback (APRV-02, Phase 23) | - |
| F-128 | MEDIUM | PARTIAL | Credential loader and DEMO/LIVE separation exist (D072, distinct variable names, paper refuses any `BINANCE_*`). Key restrictions are still not read: `src/adapters/binance_usdm.py:569-570` "canWithdraw ... are not read: the no-withdraw check is an owner attestation (OPS-02, D-21)"; no `apiRestrictions` check anywhere in src | G-1752 |

### LOW spot check (15 of 22 primary LOW)

| Old id | Old sev | Verdict | Evidence (snapshot) | Note / G-id |
|---|---|---|---|---|
| F-052 | LOW | FIXED | AGENTS stack row (`AGENTS.md:219`) "secret URL path + source-IP allow-list; TradingView cannot sign requests"; SECURITY_AND_OPERATIONS:10 | - |
| F-053 | LOW | FIXED | `docs/integration/BINANCE.md:47-53` `/public`, `/market`, `/private` paths; X10 F20/F27/F41 VERIFIED the SDK route `wss://fstream.binance.com/private/stream` | - |
| F-056 | LOW | FIXED | MARKET_LOT_SIZE / PERCENT_PRICE now in `src/domain/lot_filters.py`, `src/execution/lot_split.py`, `src/execution/tp_sizing.py`, `src/execution/constraint_snapshot.py` | - |
| F-058 | LOW | FIXED | `src/adapters/binance_usdm.py:678-690` `_decimal_to_wire` = `format(value, "f")`, used for trigger price and quantity (1571,1575) | - |
| F-003 | LOW | OPEN (KNOWN: X09 G-2105) | BTC marginal at 500-1000 USDT, canary cannot trade BTC | see G-2105 |
| F-019 | LOW | PARTIAL | Code is aware of exchange-placed liquidation/ADL orders (`src/adapters/binance_userdata_events.py:118`, `src/execution/day_risk_service.py:409`, `src/execution/liquidation_watch.py`); GLOSSARY still has no ADL entry | - |
| F-020 | LOW | FIXED | One-way single-asset only: Hedge refused (`HEDGE_MODE_UNSUPPORTED`, `pre_placement.py:56`), multi-asset refused (`BLOCKED_MULTI_ASSETS_MODE`, `margin_guard.py:501`, D086) | - |
| F-025 | LOW | OPEN | `docs/research/families/trend-pullback.md:212` "the kill gate is ... D013 (three families x six months of forward evidence)" and 222 "The V1 family is decided after **all three families** (A, B, C) clear", still contradicting D030 / RESEARCH_PROTOCOL G1-G5 (one passing candidate suffices) | hygiene (wording; protocol wins by D031) |
| F-027 | LOW | PARTIAL | `docs/operations/SECURITY_AND_OPERATIONS.md:7` still "Prefer IP allowlisting where practical"; RUNBOOK:352 requires it for the host key; no code check | G-1752 |
| F-028 | LOW | OPEN | `docs/research/RESEARCH_PROTOCOL.md:124` `entry_fee` "basis points per side" while params store fractions; harmless because the loader refuses any rate above 0.01 (RISK_MANAGEMENT:55) and the protocol is frozen | hygiene |
| F-029 | LOW | FIXED (code), doc silent | Rounding directions in code: limit snapped LONG floor / SHORT ceil (`src/backtest/entry.py:4`), SL trigger snapped toward the entry (`exits.py` `sl_trigger_price`), TP via `quantize_price(direction=tp_rounding)` (`placement.py:366-376`); RISK_MANAGEMENT lists the tick only as a constraint | - |
| F-110 | LOW | FIXED | `docs/GLOSSARY.md:150-188` section 9 one canonical code per concept, scan gate GL-02 | - |
| F-114 | LOW | OPEN | `.planning/ROADMAP.md:1590-1594` progress table: Phase 21 "5/16 In progress", Phase 22 "0/TBD Not started" although D084-D087 and `src/execution/margin_guard.py` (Phase 22, D085) exist; `.planning/STATE.md:669` lists D055 as OPEN although D079 closed it | folded into G-1751 |
| F-117 | LOW | FIXED | AGENTS now states FastAPI "is a recommended web edge that is **not installed**" | - |
| F-122 | LOW | FIXED | `src/data/backfill_cli.py:83,794` calls `backfill_universe` | - |

### Tally

HIGH/MEDIUM primary (61): FIXED 42 (F-022 counted FIXED within run 1; F-108, F-111 with a hygiene residual), SUPERSEDED 5 (F-958, F-952, F-103, F-112, F-113), PARTIAL 11 (F-023, F-960, F-018, F-014, F-908, F-956, F-109, F-124, F-101, F-115, F-128), OPEN 3 (F-953 owned by Phase 26 and unreachable now, F-107, F-121), WRONGLY_CLOSED 0. All 6 old HIGH (F-007, F-022, F-902, F-104, F-120, F-126) are closed in code or docs.
LOW spot check (15): FIXED 9, PARTIAL 2 (F-019, F-027), OPEN 4 (F-003 known as X09 G-2105, F-025, F-028, F-114).
Pattern: the planning items answered by D031-D046 and Phases 11-24 are really closed in docs AND code. What stays open is evidence only a host or the owner can produce (OI collection, PostgreSQL restore, CI on a remote, key restrictions), and the status fields that still report those as Complete.

## Coverage

| File | Level | Note |
|---|---|---|
| `.planning/audits/2026-09-29-deep-audit/findings.json` | DEEP_READ | all 94 F-0xx/F-1xx/F-9xx entries listed; 61 H/M primary judged, 15 LOW spot-checked |
| `docs/DECISIONS.md` | NORMAL_READ | D001-D114 titles; D059, D078, D092, D102 in full |
| `docs/trading/RISK_MANAGEMENT.md` | NORMAL_READ | sections 1-4 |
| `docs/trading/EXECUTION_SPEC.md` | NORMAL_READ | sections 5-6.3, 12 |
| `docs/integration/BINANCE.md` | NORMAL_READ | WS paths, working type, fee rule |
| `docs/integration/TELEGRAM.md` | NORMAL_READ | APPROVE / money block |
| `docs/operations/SECURITY_AND_OPERATIONS.md` | NORMAL_READ | sections 1, 5, 7 |
| `docs/research/RESEARCH_PROTOCOL.md` | NORMAL_READ | header, cost fields, G1-G5 |
| `docs/research/universe/research-universe-v1.toml`, `docs/research/holdout_consumed.json` | NORMAL_READ | - |
| `docs/research/families/trend-pullback.md` | METADATA_ONLY | grep kill-gate wording |
| `docs/testing/TESTING_STRATEGY.md` | NORMAL_READ | section 8 |
| `docs/GLOSSARY.md`, `docs/DOC_STATUS.md` | METADATA_ONLY | grep |
| `.planning/ROADMAP.md` | NORMAL_READ | Phase 16 SC, Phase 26, progress table |
| `.planning/STATE.md`, `.planning/REQUIREMENTS.md` | NORMAL_READ | open items; DATA/RISK/OPS rows |
| `config/execution/execution-limits-v1.toml` | DEEP_READ | - |
| `.github/workflows/research-gate.yml` | DEEP_READ | identity and tripwire steps |
| `tests/fixtures/phase4/parameters.json` | METADATA_ONLY | probe: pins vs params TOMLs |
| `src/execution/enablement.py`, `src/live/enablement.py` | DEEP_READ | enable paths |
| `src/execution/gates.py`, `src/execution/pre_placement.py`, `src/execution/placement.py` | NORMAL_READ | headroom, refusal codes, TP sizing 360-420 |
| `src/execution/protection.py`, `src/execution/emergency_close.py` | NORMAL_READ | module docstrings, SAFE_MODE use (grep) |
| `src/execution/margin_guard.py`, `src/risk/portfolio.py`, `src/risk/cost_guards.py` | METADATA_ONLY | grep |
| `src/live/risk_inputs.py` | NORMAL_READ | header, algo count |
| `src/adapters/binance_usdm.py`, `src/adapters/binance_client.py` | NORMAL_READ | algo placement 1495-1581, accountConfig 560-575, wire format, environment rows |
| `src/backtest/engine.py`, `entry.py`, `exits.py`, `funding.py`, `semantics.py`, `lifecycle.py` | NORMAL_READ | headers and cited functions |
| `src/paper/attribution.py`, `src/adapters/paper_ws.py`, `src/reconcile/safe_mode.py`, `src/ops/backup.py`, `src/data/backfill_cli.py` | NORMAL_READ | cited lines |
| Lane files `decisions_trading_soundness.md`, `exchange_facts.md`, `core_strategy_risk.md`, `live_risk_state.md`, `reconcile_safemode.md`, `telegram_alerts.md` | NORMAL_READ | leads only, re-checked in code |

## Verified Safe Areas

- No old HIGH of the docs/planning lanes is still open: F-007 (pre-placement mark/last price checks, `src/execution/pre_placement.py`), F-022 (numeric gates and one Holm, RESEARCH_PROTOCOL 281-295), F-902/F-120 (trade-through fill, N+1 activation, `src/backtest/entry.py`, `engine.py:18-19`), F-104 (user-data stream), F-126 (exactly-once entry intent) are closed in code, not only in plans.
- SAFE_MODE never blocks a protective or reduce-only action: protection and emergency close only enter SAFE_MODE and never test it; the entry pipeline tests it (`src/execution/manager.py:600`).
- Live enablement cannot be reached outside DEMO: the only `.enable(` caller is `enable_demo`, which raises for LIVE/TESTNET (`src/live/enablement.py:234-253`); the still-negative kill-gate check (F-953) therefore cannot open LIVE today.
- The 200 conditional-order headroom counts ALL open algo orders of the account (`src/live/risk_inputs.py:26-28,592,722`; `src/execution/gates.py:182`).
- Cost model units: quote per unit per leg, taker entry, live per-side max(parameter, account taker) fee (RISK_MANAGEMENT 2-3, BINANCE.md:173).
- Money/safety execution limits are set (non-null), and the live path refuses any NOT_CONFIGURED key except four alert- or refinement-only keys (`config/execution/execution-limits-v1.toml:24-39,45-81`).
- Registry gate: all 73 parameter TOMLs are pinned (probe over `tests/fixtures/phase4/parameters.json`, 0 missing).

## Decision review

| Decision / rule | Verdict | Yardstick | Reason |
|---|---|---|---|
| D036 entry fee modeled as taker | SOUND | risk practice | conservative; closes F-005 |
| D037 MARK_PRICE triggers, backtest on mark klines | SOUND | exchange docs (X10), logic | one trigger series in live and backtest; closes F-010/F-958 |
| D038 partial_fill_fraction 1.0 | SOUND | research practice | removes the 50 % artefact of F-006 |
| D039/D049 point-in-time universe incl. delisted | SOUND | research practice | removes survivorship bias (F-024/F-907) |
| D045 descoping of trades / feature_snapshots / experiment_runs | SOUND | logic | explicit record instead of silent omission (F-112) |
| D052 TP1 fraction a semantics constant, not a registry key | SOUND | logic | one constant read by backtest and live; a change moves the semantics version (F-103) |
| D061 item D paper exit = engineering-parity gate, no trade count | DOUBTFUL | research practice | answers F-023 by narrowing it: the forward period checks plumbing, not that realized costs, fill rate and approval delay match the model; edge evidence rests on research run 1 alone (X09 G-2101) |
| D-21 / OPS-02 key restrictions by owner attestation only | DOUBTFUL | owner goals (fail closed, part-time), loss arithmetic | G-1752: a withdraw-enabled or non-IP-restricted key is the one failure that can lose the whole balance, and the adapter already receives `canWithdraw` and discards it |
| D092 Demo-only WITHIN_BUDGET kill-gate state | SOUND for Demo | logic | bounded to DEMO by `enable_demo`; the LIVE requirement is Phase 26 SC1 |

## Findings

### G-1750
- **ID:** G-1750
- **Severity (now / mainnet):** LOW / LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** CI / research governance
- **Component:** `.github/workflows/research-gate.yml`, `docs/DOC_STATUS.md`
- **File / Lines:** `.github/workflows/research-gate.yml:76-140`; `docs/DOC_STATUS.md:13,53`
- **Rule:** old F-101 ("retarget ... or stop citing them as enforcement")
- **Known-prior:** F-101; `.planning/STATE.md` open item "Research-gate as a required status check on master, or a recorded waiver: ROADMAP Phase 26 item G1-001"; 13.1-CONTEXT D-01 "research-gate.yml stay as they are"
- **Evidence:** the identity step searches files named `experiment*.json|yaml` / `backtest*.json|yaml` and greps camelCase keys (`strategyVersion parameterSetId ...`); the 480 committed records are `docs/research/experiments/research-run-1*/<sha256>.json` with snake_case keys (`parameter_set_hash`, `cost_model_hash`), so the step always takes the "passes vacuously" branch. The tripwire greps JSON/YAML for a parameter-set id, while every parameter set is TOML under `params/`. DOC_STATUS:13 "executable gate at `.github/workflows/research-gate.yml`", :53 "three fail-closed checks".
- **Expected:** a cited gate checks what it says, or the docs stop citing it.
- **Actual:** two of three checks can never fail; only the freeze check works. Identity fields are in fact enforced by the record type (`src/backtest/experiment.py:106-116,253-258`).
- **Reproduction:** in the snapshot, `find . -name 'experiment*.json' -o -name 'backtest*.json'` returns nothing.
- **Impact:** none on money; readers trust a CI gate that cannot fail.
- **Why tests miss it:** the workflow is not exercised by pytest; the vacuous branch exits 0 by design.
- **Remediation:** retarget identity to `docs/research/experiments/**/*.json` with snake_case keys and the tripwire to `params/**/*.toml`, or mark the two steps inert in DOC_STATUS.

### G-1751
- **ID:** G-1751
- **Severity (now / mainnet):** LOW / MEDIUM
- **Confidence:** CONFIRMED (status text) / UNVERIFIED (host reality, not in the repo)
- **Classification:** DRIFT
- **Category:** requirements / status reporting
- **Component:** `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`
- **File / Lines:** `.planning/REQUIREMENTS.md:19,21,129,131`; `.planning/ROADMAP.md:299,344,1576-1577,1590-1594`; `.planning/STATE.md:669-671`
- **Rule:** old F-107, F-121, F-124, F-114 (re-classify until evidence exists)
- **Known-prior:** F-107, F-121, F-124, F-114; ROADMAP Phase 26 SC2/SC3 own the evidence (restore drill, re-verification), not the status fields
- **Evidence:** DATA-02 "collects OI snapshots continuously ... so the 30-day API window never destroys research data" and DATA-04 "passes an automated backup + restore drill covering PostgreSQL state" are `[x]` / Complete. The repo holds no evidence of continuous OI ingestion (`STATE.md:671` "until it exists the collector runs on a dev machine"; `16-37-consistency.md:55` "There is NO `data_class=oi` directory (open interest) locally"; D059(4) "the repository cannot enforce the date") and no evidence of any real `pg_restore` (none in `.planning/phases/*/evidence`; D064 real-S3 gate "result pending until the owner runs it", STATE:637). ROADMAP still shows 08-02/09-04 `[x]` and Phases 8/9 Complete, Phase 22 "0/TBD Not started" although D085 and `src/execution/margin_guard.py` exist; STATE:669 still lists D055 as OPEN although D079 closed it.
- **Expected:** a requirement is Complete only with evidence (the project's own D061 item J closure rule), and status tables agree with DECISIONS.
- **Actual:** the 2026-09-29 asks to reopen these statuses were not applied; the evidence moved to Phase 26 but the ticks stayed.
- **Reproduction:** read the cited lines.
- **Impact:** now: the owner reads "backups restore" and "OI collected" as done; an OI gap is unrecoverable after 30 days (D009/D017), and an untested restore is the classic backup failure. Mainnet: the first real restore would happen after a host loss. No trading decision reads OI today (`src/core` has no OI input).
- **Why tests miss it:** status markdown is not checked against evidence.
- **Remediation:** set DATA-02 and DATA-04 to Partial pointing at the Phase 26 SC3 drill and an OI coverage report; refresh the ROADMAP progress table and the STATE "Open user decisions" list.

### G-1752
- **ID:** G-1752
- **Severity (now / mainnet):** LOW / MEDIUM
- **Confidence:** CONFIRMED (code) / PROBABLE (meaning of `canWithdraw` in accountConfig, see Open Questions)
- **Classification:** DESIGN
- **Category:** security / credentials
- **Component:** `src/adapters/binance_usdm.py`, OPS-02, `docs/operations/SECURITY_AND_OPERATIONS.md`
- **File / Lines:** `src/adapters/binance_usdm.py:564-575`; `docs/operations/SECURITY_AND_OPERATIONS.md:5-7`; `docs/operations/RUNBOOK.md:352`
- **Rule:** old F-128 (startup check of key restrictions that fails closed), F-027 (IP allowlist only "preferred")
- **Known-prior:** F-128, F-027; OPS-02 Pending; D-21 (Phase 21) records the attestation choice
- **Evidence:** "The other fields of the response (canWithdraw, canTrade, feeTier, ...) are not read: the no-withdraw check is an owner attestation (OPS-02, D-21), not an adapter read." No `apiRestrictions` / `ipRestrict` / `enableWithdrawals` read exists in `src/`. SECURITY section 1 still reads "Prefer IP allowlisting where practical" while RUNBOOK:352 requires it.
- **Expected (owner goals: fail closed, one part-time operator):** the live process refuses to start when its key can withdraw or is not IP-restricted, since that misconfiguration can lose the whole account rather than one trade's risk.
- **Actual:** correctness depends on a one-time human attestation; a later key rotation (RUNBOOK) can silently drop the restriction.
- **Reproduction:** grep `withdraw|ipRestrict|apiRestrictions` in `src/` (only the docstring above).
- **Impact:** now none (Demo keys, placement disabled). Mainnet: a leaked withdraw-enabled key means loss of the whole balance, independent of every risk gate.
- **Why tests miss it:** there is no code to test; the attestation is a checklist item.
- **Remediation:** owner decision (below): read `GET /sapi/v1/account/apiRestrictions` at live start and refuse unless `enableWithdrawals` is false and `ipRestrict` is true, or record in DECISIONS why attestation suffices and re-attest at each key rotation; change SECURITY section 1 "Prefer" to "must".

## Owner decisions

1. **Key restriction check (G-1752).** Option A: the live process checks the key restrictions at start and refuses a withdraw-enabled or non-IP-restricted key (one extra signed GET per start). Option B: keep the attestation and repeat it at every key rotation. Example: with 1,000 USDT in the account, a leaked unrestricted key can move all 1,000 USDT; every risk gate of the project bounds one trade to about 5 USDT (0.5 %).
2. **Status of DATA-02 / DATA-04 (G-1751).** Mark them Partial now, or keep the tick until Phase 26. Each day of OI not recorded is lost for good after the 30-day API window.
3. **Paper exit gate scope (F-023 / D061 item D).** Whether the forward period should also compare realized fill rate, slippage and approval delay with the modeled values before CANARY, or leave cost calibration to the Demo campaign (Phase 25) and the canary (Phase 26).

## Open Questions

- For X05 (docs vs code), stale sentences found while checking closures: `docs/operations/SECURITY_AND_OPERATIONS.md:88` and section 7 "Implementation status (Phase 20) ... not run by any deployed process yet: the composition is Phase 24" (the composition exists); `docs/trading/EXECUTION_SPEC.md:145` "Both keys are `NOT_CONFIGURED`" although `max_unprotected_ms = 180000` and `entry_terminal_timeout_ms = 900000` are set (limits:46-47); `src/ops/backup.py:17-24,33-37` docstring ("pg_restore is left to the operator", `BACKUP_TARGET` read nowhere); `docs/testing/TESTING_STRATEGY.md:114,123` pseudo-state and "awaiting user confirmation".
- For X10: does `canWithdraw` in `GET /fapi/v1/accountConfig` reflect the API key's withdrawal permission or the account's? If the key's, G-1752 option A needs no spot-domain call.
- For X02/X03: the backtest turns an un-sizeable TP1 leg into a NO_TRADE (`src/backtest/exits.py:306-329`), live turns it into TP_UNAVAILABLE + SAFE_MODE with the stop kept (`src/execution/protection.py:107-108`); with full fills (D038) this diverges only on live partial fills, and the parity is not documented.
- Not inspected: whether CI runs on a GitHub remote (Phase 26 SC4); host state of the OI collector and of backups (not in the repo).

## DONE
