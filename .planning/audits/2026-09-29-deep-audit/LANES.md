# LANE ASSIGNMENTS (lane-specific focus; common rules in LANE_BRIEF.md)

## L1 requirements_docs_plan — IDs F-101..F-199 — file `lanes/requirements_docs_plan.md`
Goal: are the original docs themselves right and consistent, and did requirements → plans → code actually line up?
- Docs internal consistency: docs/* vs docs/* vs AGENTS.md vs .planning/PROJECT.md/REQUIREMENTS.md. Stale claims (e.g. stack versions, endpoint names), contradictions, undefined terms, TBDs, rules specified for backtest but silent for live. Also design flaws in the docs themselves (e.g. a sizing formula that's dimensionally wrong, a risk rule that can't be satisfied with $500 capital, approval rule that is unimplementable).
- Requirements traceability matrix: every REQ-ID in `.planning/REQUIREMENTS.md` → phase(s) in ROADMAP → PLAN(s) → SUMMARY claims → code location → test. Mark: IMPLEMENTED+TESTED / IMPLEMENTED-UNTESTED / PARTIAL / CLAIMED-BUT-MISSING / NOT-STARTED / NO-REQUIREMENT (code with no documented rationale). Spot-check SUMMARY claims against code (at least 2 claims per phase 02–10).
- Docs requirements that never became REQ-IDs (lost requirements). ROADMAP success criteria vs VERIFICATION.md.
- Gray areas: decisions left in CONTEXT/DISCUSSION-LOG as "Claude's discretion"/deferred that affect money/safety; `deferred-items.md`.
- Put the traceability matrix in the lane file (appendix).

## L2 architecture_code — IDs F-201..F-299 — `lanes/architecture_code.md`
Goal: structure vs docs/architecture/ARCHITECTURE.md + DATA_PIPELINE.md, and whether a runnable system exists.
- Layering rules: pure core (src/core, src/domain, src/risk) must not import I/O/SDK/Polars/FastAPI/DB; SDK types must not leak past src/adapters; ORM models not used as domain models. Build the actual import graph (python ast probe in tmp) and list violations.
- Entry points: what can actually be run (CLI `__main__`, scripts, Dockerfile CMD, docker-compose services)? Is there a composition root wiring signal→plan→notify→approve→execute→protect→reconcile→journal? (Known: M1–M3 from v0.3 audit — confirm/extend, find anything else unwired, dead modules, functions with zero callers outside tests.)
- Duplicate logic between backtest/paper/live (the invariant says identical logic — find forks: sizing, quantization, cost model, fill semantics, expiry).
- Any-typed seams, protocol mismatches, error-handling style (exceptions swallowed, broad except), Decimal/float boundaries across modules (float in any path that gates an order).
- Config/param loading: params/*.toml → registry → runtime; hard-coded values that should be config (symbols, quote asset, timeouts).

## L3 business_invariants — IDs F-301..F-399 — `lanes/business_invariants.md`  (MOST IMPORTANT LANE — go deep)
Goal: for each money/safety invariant in INVARIANTS.md, trace every entry point and prove enforced or violated. Write probe scripts that import snapshot code with concrete numbers (e.g. equity $500/$1000, BTC 60k, SL 1%/3%, ETH, low-price alts) to demonstrate.
- Sizing: src/risk/sizing.py, quantization.py, portfolio.py, gating.py; cost model src/backtest/costs.py (known fee-unit bug — quantify the actual error in $ and % across scenarios; check whether ANY other path has the same unit bug, e.g. realized-risk check, PnL, R-multiple, exit fees, funding).
- Portfolio limits: max open positions, aggregate open risk, daily loss stop (how is daily loss computed? timezone/day boundary? realized+unrealized? fees included?), correlation/same-symbol rules.
- Planner/strategy: src/core/planner.py, strategy.py, features.py — entry/SL/TP geometry per direction (long/short sign errors), R:R, invalidation, expiry, closed-candle-only, no lookahead, tick rounding direction (SL rounding must not reduce protection / increase risk).
- Approval: src/approval/* + src/domain/approval.py + adapters/telegram_callbacks.py — expiry, one-time token, replay, stale plan/constraints, authorized chat/user, race of two approvals, approve after position already opened, approve after kill-gate disabled/SAFE_MODE.
- Execution: src/execution/* — gates before placement (enablement, SAFE_MODE, kill gate, constraints freshness), entry order type, protective SL/TP via algoOrder placed atomically/immediately, what if entry fills but SL placement fails, partial fills → protective qty, clientOrderId idempotency, reduceOnly/closePosition, position mode.
- Reconcile / SAFE_MODE: src/reconcile/* — mismatch → SAFE_MODE; does SAFE_MODE actually block every entry path; exit from SAFE_MODE.
- Kill gate: src/analytics/killgate.py, gates.py — sticky, cannot be bypassed.
- Parity: same inputs through backtest vs paper vs live paths give same plan/size.

## L4 data_database_concurrency — IDs F-401..F-499 — `lanes/data_database_concurrency.md`
- src/db/models.py, mappers.py, alembic env + versions vs docs/data/DATA_MODEL.md: missing tables/columns/constraints (unique, FK, check), nullable money fields, Decimal precision/scale (Numeric) vs exchange precision, timezone-aware timestamps, enum drift between domain enums and DB, migration chain linearity & downgrade, `scripts/check_migration_parity.py`, any `create_all` in prod paths.
- Transaction boundaries: approval state change + order intent persisted atomically? idempotency keys unique in DB? race: concurrent callback handling, double-submit, at-least-once replay under concurrency (DB-level guard vs in-memory).
- asyncio concurrency: shared mutable state in paper/supervisor/loop, fill_monitor, sweeper; cancellation handling; tasks never awaited; blocking I/O in event loop.
- Data pipeline: src/data/* (backfill, collector, store, quality, coverage, metadata) — raw immutability, derived versioning, dedupe, gaps, candle close-time semantics, timezone, Parquet schema types (float vs Decimal for prices), DuckDB SQL src/sql/coverage_v1.sql.
- Journal: src/paper/journal.py, src/domain/journal.py, analytics_store — append-only? replay-safe?

## L5 integrations_external_apis — IDs F-501..F-599 — `lanes/integrations_external_apis.md`
- src/adapters/binance_usdm.py vs docs/integration/BINANCE.md vs the INSTALLED SDK (`C:\Users\admin\Music\Trading\.venv\Lib\site-packages\binance_sdk_derivatives_trading_usds_futures\` — read-only; verify method names, parameter names, enum values, response field names actually exist in SDK 17.4.0). Algo order params (algoType=CONDITIONAL, triggerPrice, workingType, priceProtect, reduceOnly/closePosition), exchangeInfo filters (PRICE_FILTER, LOT_SIZE vs MARKET_LOT_SIZE, MIN_NOTIONAL key name `notional`), position mode detection, 200 conditional headroom, recvWindow/timestamp, rate limits/429/418 handling, -1021/-2019/-4164 etc error mapping, user-data WS (listenKey keepalive, ALGO_UPDATE, ORDER_TRADE_UPDATE, ACCOUNT_UPDATE), reconnect/backoff.
- src/adapters/paper_ws.py market streams: closed-kline detection (`x` flag), reconnect gaps + resync.
- Telegram: telegram_notify.py / telegram_callbacks.py vs docs/integration/TELEGRAM.md: callback_data size (64 bytes), authorized chat/user check, answerCallbackQuery, message edit after decision, notification failure → no auto approve, retry/tenacity bounds, MarkdownV2 escaping.
- TradingView: docs/integration/TRADINGVIEW.md vs code (is the webhook implemented at all? HMAC? FastAPI edge exists?).
- Any direct HTTP (httpx) usage; timeouts set?

## L6 testing_verification — IDs F-601..F-699 — `lanes/testing_verification.md`
- Interpret `AUDIT\tool-output\*` (ruff, format, mypy strict, pytest results incl. skips and durations). Verify significant tool findings against code.
- Test quality, not coverage %: for the critical behaviors (sizing, quantization, approval expiry/replay/stale, execution failure paths, SAFE_MODE, reconcile mismatch, kill gate, daily loss stop, fee/cost units, WS reconnect, restart/recovery, migrations) — is there a test that would FAIL if the behavior broke? Look for tautological tests, tests that assert on mocks only, golden fixtures that were regenerated from buggy code (e.g. `scripts/_regen_phase4_expectations.py`, `gen_phase6_fixtures.py` — are expectations derived from the implementation itself?), fixtures encoding the fee-unit bug.
- Skipped tests (PG gated) → what is never exercised. No integration/E2E tests. CI workflows (.github/workflows/*) — what runs in CI, what doesn't (mypy? full pytest? PG?).
- VALIDATION.md / Nyquist claims vs reality for phases 07, 08, 09, 10.
- Describe reproduction steps for unprotected behaviors; do NOT create tests.

## L7 security_reliability — IDs F-701..F-799 — `lanes/security_reliability.md`
- Secrets: .env.example, settings loading, logging of secrets/API keys/DB URLs (redaction), structlog config, exception messages; API key permission scope guidance (withdraw disabled, IP whitelist) in docs vs code checks.
- Auth: Telegram authorized chat/user enforcement on every callback; approval token entropy/predictability (src/approval/tokens.py), HMAC compare constant-time, webhook replay protection.
- Fail-closed audit: every except/timeout/None-path on the order path — does it end in NO_TRADE/SAFE_MODE or continue? Clock skew handling. Stale data detection (feed gates).
- Ops: src/ops/backup.py, drills.py, health.py, scripts/backup-drill.ps1, docs/operations/RUNBOOK.md + SECURITY_AND_OPERATIONS.md — backups off-host? restore tested? health checks meaningful? Dockerfile (non-root user? pinned base image?), docker-compose (exposed ports, default passwords).
- Dependency hygiene: pyproject pins vs uv.lock versions (read uv.lock), deprecated packages, known-vuln versions if you can judge offline (mark UNVERIFIED if not).
- Restart/recovery: process crash between entry fill and SL placement; restart with open positions; idempotent restart.

## L8 historical_regression — IDs F-801..F-899 — `lanes/historical_regression.md`
Goal: cross-phase regressions and plan↔commit drift using git history (591 commits).
- Map phases → commits (`git log --oneline`, commit message prefixes like `feat(05-01)`, `fix(08)`), note commits touching src/ without a phase/plan reference.
- For key invariants (sizing, cost model, quantization, approval binding, SAFE_MODE, kill gate, registry/cost binding B1), trace: which phase established it (PLAN/SUMMARY + commit) → later commits that modified the same functions (`git log -L`, `git log -S`, `git blame`) → does current code still satisfy the original contract/test? Especially REVIEW-FIX commits (they change behavior late, sometimes contracts): phase 10 fixes CR-01, WR-04, WR-05 (exit code 3), WR-07, WR-08, WR-09, WR-11 — did they break earlier-phase callers/tests/docs?
- Tests that were modified/deleted/loosened alongside code changes (`git log -p -- tests/` with weakened asserts, xfail/skip added, tolerances widened, expectations regenerated).
- Golden fixtures regenerated after behavior change (who regenerated, was the change justified in a plan?).
- When was the fee-unit bug introduced and did any review/verification miss it? (`git log -S modeled_costs_per_unit`).

## STAGE C NOTE (all code lanes L2–L8)
Before auditing code, read `lanes/docs_trading_soundness.md` ("Corrected Rules for Code Audit"), `lanes/docs_exchange_facts.md` ("Exchange Facts for Code Audit"), and the planning lanes' QUESTIONABLE/WRONG decisions. Judge code against the corrected rules. When code faithfully implements a WRONG doc rule, report it (classification DEFECT, note "root cause: doc/plan F-0xx/F-9xx") rather than calling the code correct.

---
# STAGE A / B LANES (added after user scope update — CHARTER §11). Docs are AI-generated: judge them, don't trust them.

## A1 docs_trading_soundness — F-001..F-049 — `lanes/docs_trading_soundness.md`
Role: a senior crypto-futures risk manager and quant-research methodologist, reviewing a design that an AI wrote.

**Read:**
- all of docs/, especially:
  - 00_PRODUCT_SCOPE, 01_ENGINEERING_PRINCIPLES, DECISIONS
  - strategy/TRADING_STRATEGY_SPEC
  - trading/RISK_MANAGEMENT, EXECUTION_SPEC, SIGNAL_AND_ALERTS
  - backtest/BACKTEST_SPEC, METRICS
  - research/*, configuration/CONFIGURATION, operations/*
- params/**/*.toml
- INVARIANTS.md: its "Domain soundness" flags and the "Candidate Doc-Design Concerns" section

**Task:** judge whether the DESIGN is correct and safe for a part-time retail trader with $500–1,000 on Binance USD-M perpetuals.

**Risk and sizing math**
- dimensional correctness (a fee rate vs a $ amount)
- risk per trade vs minNotional/minQty at this capital: which symbols and SL distances end up as NO_TRADE?
- the 60% realized-risk rule
- aggregate risk
- daily loss stop definition: UTC day? realized PnL only?
- leverage, margin mode and liquidation distance: are they specified anywhere?
- funding cost
- how realistic the slippage model is
- maker vs taker assumption vs the entry type actually used (limit / market / stop-entry)
- fee tiers and BNB discount
- USDC pairs

**Execution design**
- entry order type and its expiry
- what happens between signal and approval (price may move past entry or SL)
- partial fills
- SL/TP via algo conditional orders: workingType MARK vs CONTRACT, priceProtect
- rounding of TP-ladder quantities
- breakeven and trailing rules
- liquidation hit before the SL, ADL
- one-way vs hedge mode

**Approval UX**
- does the human get enough information to decide: qty, $ risk, margin?
- are the expiry windows sensible for 4H/1H candles and a trader with a full-time job?

**Methodology** (profitability is out of scope)
- no-lookahead, closed-candle, warm-up
- 1m intrabar ambiguity when SL and TP hit in the same bar
- cost realism
- multiple testing and selection bias
- kill-gate sample size
- walk-forward / OOS
- paper-soak duration vs statistical power
- survivorship in the symbol universe

**Ops/safety**
- SAFE_MODE triggers
- reconciliation frequency
- API key permissions
- backups

**Each concern must include:**
- the quoted doc text
- the trading reality
- severity (the consequence if implemented as written)
- confidence
- a concrete corrected rule

Classification:
- DEFECT: the doc's design is wrong
- GAP: the doc is silent on a necessary rule
- AMBIGUITY: the rule is unclear

**Required sections:**
- `## Doc Rules Verified Sound`
- `## Corrected Rules for Code Audit`: a numbered list, with INV refs. Each entry states one of:
  - "doc correct"
  - "doc wrong → use X"
  - "doc silent → minimum safe rule X"

Web reading of public sources (Binance FAQ on margin, liquidation, funding and fees) is allowed via WebSearch/WebFetch. Cite URLs.

## A2 docs_exchange_facts — F-051..F-099 — `lanes/docs_exchange_facts.md`
**What to verify:** every factual external claim in:
- docs/integration/BINANCE.md, TELEGRAM.md, TRADINGVIEW.md
- docs/TECHNOLOGY_STACK.md, docs/SOURCES.md
- the stack table in AGENTS.md
- the exchange facts inside trading/EXECUTION_SPEC.md and RISK_MANAGEMENT.md

**Verify against (1): CURRENT official docs on the web**
- developers.binance.com, USDⓈ-M Futures:
  - new/query/cancel algoOrder
  - exchangeInfo filters (PRICE_FILTER, LOT_SIZE vs MARKET_LOT_SIZE, MIN_NOTIONAL)
  - commissionRate
  - account v3, balance v3, positionRisk v3
  - leverage, marginType
  - positionSide / dualSidePosition
  - listenKey + user-data events: ALGO_UPDATE, ORDER_TRADE_UPDATE, ACCOUNT_UPDATE
  - rate limits, error codes, change log
- core.telegram.org/bots/api: callback_data 1–64 bytes, answerCallbackQuery, parse modes
- TradingView webhook docs

**Verify against (2): the INSTALLED SDK** (17.4.0, read-only) at `C:\Users\admin\Music\Trading\.venv\Lib\site-packages\binance_sdk_derivatives_trading_usds_futures\`
- method names
- param names
- enums
- response models

**Also verify:** the current USD-M fee schedule (VIP0 maker/taker for USDT-M vs USDC-M perps, BNB discount) vs params (fee_rate_entry 0.0002, fee_rate_exit 0.0005) and vs the docs.

**Output:**
- a table with columns: claim → doc location → official URL / SDK file → status (CORRECT / STALE / WRONG / UNVERIFIABLE)
- findings only for WRONG/STALE claims that matter
- `## Exchange Facts for Code Audit`: verified endpoints, params, field names and limits that the code lanes must use

## B1 planning_decisions_01_06 — F-901..F-949 — `lanes/planning_decisions_01_06.md`
## B2 planning_decisions_07_17 — F-951..F-999 — `lanes/planning_decisions_07_17.md`
Inputs:
- lanes/docs_trading_soundness.md
- lanes/docs_exchange_facts.md
- INVARIANTS.md

Phases per lane:
- B1: 01, 02, 03, 04, 05, 06
- B2: 07, 07.1, 08, 09, 10, plus the ROADMAP goal definitions of 11–17 (they have no plans yet)

Read, per phase:
- CONTEXT
- DISCUSSION-LOG
- RESEARCH
- PLANs (skim)
- REVIEW, REVIEW-FIX, REVIEW-DISPOSITION, VERIFICATION, VALIDATION, deferred-items

Context: the user has little trading expertise and let the AI auto-pick the "recommended" options.

What to produce:
- **Decision register** (appendix table): every D-xx, gray area, "Claude's discretion", auto-selected option and deferral. Columns:
  - what was chosen
  - alternatives
  - verdict: SOUND / QUESTIONABLE / WRONG / RISKY-DEFERRAL
  - reasoning grounded in trading reality and the stage A corrected rules
- **Findings** only for QUESTIONABLE, WRONG or RISKY-DEFERRAL decisions with a real consequence: money, safety, research validity, or a later phase built on a wrong base. Also flag:
  - decisions that contradict the docs or the corrected rules
  - research that cited stale or wrong exchange facts
  - review findings that were skipped or accepted but still matter
  - orphaned deferrals (never picked up by a later phase)
- **B2 only:** are the goal definitions of 11–17 correct and complete? Are phases missing (e.g. runtime composition M1–M4)? Is the dependency order wrong?

Don't audit code deeply; stage C does that. Cite code only to show the effect of a decision.
