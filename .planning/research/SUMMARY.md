# Project Research Summary

**Project:** Deterministic Binance Futures Research & Semi-Automated Execution System
**Domain:** Deterministic crypto-futures research + semi-automated execution (Binance USDⓈ-M, 4H/1H swing, human approval)
**Researched:** 2026-09-19
**Confidence:** HIGH (canonical Core Docs v0.3 + verified PyPI/official SDK versions; MEDIUM on exact numeric floors and Binance field details pending re-verification)

## Executive Summary

This is a deterministic, reproducible Binance Futures research-to-execution system for a part-time worker with $500–1,000 research capital — not a bot, not a signal group, not an HFT engine. Experts build this class of system as a pure deterministic core (features → strategy → planner → risk as pure functions) wrapped in adapters (Binance SDK, Telegram, PostgreSQL, Parquet/DuckDB), with backtest/paper/live sharing identical execution semantics so evidence transfers instead of evaporating. The recommended approach is research-first and fine-grained: freeze the strategy research protocol and parameter registry before any parameter work, bootstrap the Phase-0 data foundation immediately (OI history is irrecoverable after ~30 days), then build pure core → backtest parity engine → months-long paper forward test → cautious human-approved live rollout, with NO_TRADE as a valid kill-gate outcome.

The dominant risks are silent and methodological, not infrastructural: look-ahead/repaint contaminating backtests, intrabar SL/TP ordering fabricating edge, costs-after-selection and round-up sizing breaching the 0.5% risk budget, and the late-2025 Binance Algo-Order migration invalidating every legacy STOP_MARKET tutorial. All are mitigated by the same mechanism — golden-fixture parity tests, immutable versioned parameter sets, floor-only quantization, Algo-endpoint re-verification against current official docs, reconciliation plus orphan sweeper, and idempotent expiring Telegram approvals — enforced as CI/gate checks, not conventions.

## Key Findings

### Recommended Stack

Single-language Python 3.13 + uv system: the official `binance-sdk-derivatives-trading-usds-futures>=17.3,<18` (v17.3.1, Sep 2026) is the only sanctioned connector — legacy `binance-connector`/`binance-futures-connector` were archived 2026-04-30 and lack Algo-Order endpoints. Operational state lives in PostgreSQL 17 (SQLAlchemy 2.0.x + psycopg 3 + Alembic); research data lives in immutable Parquet + DuckDB 1.5.5 with Polars as the frame engine; FastAPI + python-telegram-bot 22.x exist only at the edge (webhook/health, SIMULATE/APPROVE/SKIP). See `STACK.md` for versions, install commands, and what-not-to-use list.

**Core technologies:**
- Python 3.13.x + uv — single implementation language; lockfile is the reproducibility mechanism; do NOT take 3.14/RC lines yet
- `binance-sdk-derivatives-trading-usds-futures>=17.3,<18` — REST/WS/user-data + `POST /fapi/v1/algoOrder` CONDITIONAL protective exits + `ALGO_UPDATE` events; adapter-isolated, never leaking into domain
- PostgreSQL 17 + SQLAlchemy 2.0 + psycopg 3 + Alembic — ACID lifecycle state (signals/plans/approvals/orders/fills/positions/journal); every schema change a reviewed migration
- Parquet (pyarrow>=19) + DuckDB 1.5.5 + Polars>=1.44 — immutable research datasets, local analytical SQL, feature/backtest computation; strategy core must not import frame libraries
- Pydantic v2 + pydantic-settings — boundary validation and versioned parameter-registry loading; secrets via env, never git
- FastAPI + uvicorn + httpx (edge) and python-telegram-bot>=22.8,<23 (approval loop) — edge-only; idempotent expiring tokens, at-least-once replay
- pytest 9 + pytest-asyncio (auto) + respx, Ruff, mypy-strict, structlog/tenacity, Docker Compose — determinism harness, lint/type gates, decision-lineage logs, bounded fail-closed retries

### Expected Features

The canonical pipeline is Market Data → Features → Strategy → Plan → Risk → Approval → Execution → Journal → Research; missing any link breaks V1. Table stakes cluster around data continuity, deterministic planning, fail-closed risk, and live safety; differentiators are cheap evidence multipliers (reproducibility harness, three-way attribution, uncertainty-first reporting). See `FEATURES.md` for the 12-capability chain, dependency graph, and P1/P2/P3 matrix.

**Must have (table stakes):**
- Market-data ingestion (REST bootstrap + WS realtime 1m/1H/4H) + reconnect/resync/warm-up/continuity — no candles, no product
- OI + funding + symbol metadata collectors from day one — OI irrecoverable outside ~30-day window; dynamic exchangeInfo snapshot per plan
- Feature engine + deterministic strategy engine (closed-candle, no-repaint, prefix-invariant, deterministic SignalId) — one family first, versioned
- Trade planner (entry zone/SL/TP/invalidation/expiry/RR/plan_hash) + risk engine (0.5% baseline, floor-only quantization, 60% floor else QUANTIZATION_REJECT, portfolio caps, DAILY_STOP) — identical in all modes
- Telegram approval (SIMULATE/APPROVE/SKIP) with idempotent expiring tokens — the part-timer's control surface
- Execution manager (LIMIT-zone entry + Algo-Order SL/TP, partial-fill handling, 4-way reconciliation + orphan sweeper + SAFE_MODE, user-data stream monitor) — live safety minimum
- Journal + analytics (system vs user vs opportunity, MFE/MAE) + backtest parity engine with validation gates (splits, walk-forward, baselines, bootstrap/MC uncertainty) + paper/forward engine (3–6 mo) + backup/restore drill + TradingView Pine cross-check

**Should have (competitive):**
- Prefix-invariant + byte-equivalence reproducibility harness — determinism as CI property
- Three-way attribution + uncertainty-first reporting (bootstrap CIs, Monte Carlo drawdown) — honest evidence for NO_TRADE courage
- Approval-latency analytics — proves 4H/1H TTLs fit a worker who can't answer in minutes
- Deterministic id / content-hash lineage (Signal→Plan→Approval→Order→Fill) — restart-safe audit trail
- Kill-gate dashboard (3 families / 6 months → NO_TRADE valid), live-vs-research universe split reporting, cost-aware sizing preview in Telegram card, RUNBOOK-rehearsed SAFE_MODE drills

**Defer (v2+):**
- LIVE_AUTONOMOUS, multi-position/hedge strategies, advanced correlation model, automated retraining/adaptive params — explicitly out of V1 scope
- 15M entry refinement, extended Telegram actions (CANCEL/CLOSE/SAFE_MODE), operational TradingView webhook — v1.x gated on paper evidence
- Anti-features (never in V1): LLM/AI decisions, daily-profit targets, HFT/scalping, order-book ML/RL, news-sentiment overrides, martingale/averaging-down, round-up sizing, auto-approve on outage, Kafka/K8s/microservices/Rust-rewrite-first, 5M as timing dependency, single-point overfit params

### Architecture Approach

Pure core + adapters at the edge, one codebase serving four modes (research/backtest/paper/live) with byte-identical decision semantics. Seven separate entities with own state machines (Signal ≠ TradePlan ≠ Approval ≠ Order ≠ Trade ≠ Position ≠ SystemMode/DailyRisk); analytical storage (immutable Parquet → DuckDB/Polars) strictly split from operational storage (PostgreSQL state + append-only journal); parameter registry immutable and hash-identified; backtest simulator reuses live core code. See `ARCHITECTURE.md` for the system diagram, `src/` layout, data flows, and 8–12-phase build order.

**Major components:**
1. Ingestion / normalization layer (`src/data/`) — candle/OI/funding/metadata collectors; SDK types stop here, project-owned frozen domain types beyond
2. Pure deterministic core (`src/features/`, `src/strategy/`, `src/planning/`, `src/risk/`, `src/domain/`) — no I/O, no network, no SDK imports; golden-fixture tested
3. Approval/alert adapter (`src/notifications/`) — Telegram SIMULATE/APPROVE/SKIP with expiring idempotent tokens
4. Execution manager (`src/execution/`) — the ONLY live-trading-endpoint caller; LIMIT entries, Algo-Order protective exits, partial fills, deterministic client IDs
5. Reconciler + orphan sweeper — startup/reconnect/periodic 4-way compare; RECONCILIATION_REQUIRED on drift; SAFE_MODE blocks entries while monitoring continues
6. Journal/analytics (`src/infrastructure/` + queries) — append-only events; system/user/opportunity joins; MFE/MAE; uncertainty
7. Backtest simulator + experiment/parameter registries (`src/backtest/`, `src/infrastructure/config`) — 1m intrabar, cost/fill/quantization parity, full identity tuple per run

### Critical Pitfalls

17 pitfalls catalogued in `PITFALLS.md`, each with phase mapping and verification. Top watch-outs below; full prevention/verification matrix lives in `PITFALLS.md` § Pitfall-to-Phase Mapping plus the "Looks Done But Isn't" checklist.

1. **Look-ahead via unclosed candles / future swing confirmation** — signal timestamp must equal confirmation-candle close, never the swing pivot; prefix-invariance CI gate; address Phase 1, re-verify Phase 2.
2. **Intrabar SL/TP ordering on 1H OHLC fabricating edge** — resolve both-touched bars with 1m data; SL-first conservative fallback + ambiguous-bar share metric; requires Phase-0 1m collection.
3. **OI history assumed backfillable beyond ~30 days** — highest time-value pitfall, irreversible; start OpenInterestCollector in Phase 0 before any OI-dependent hypothesis.
4. **Quantity rounded UP / costs added after selection** — floor-only quantization with 60% gate else QUANTIZATION_REJECT; every experiment declares fees/funding/slippage from run #1; identical sizing in backtest/paper/live.
5. **Legacy STOP_MARKET endpoint + closePosition/reduceOnly/mode misuse + orphan protectives + duplicate approvals** — Algo-Order endpoints re-verified vs current docs; explicit position-mode detection; post-fill protection confirmation; 4-way reconciliation + orphan sweeper; one-time approval tokens with deterministic client IDs and 5× duplicate-callback test.

## Implications for Roadmap

Research demands fine granularity (8–12 phases), research-first ordering (protocol/registry/fixtures before parameters), Phase-0 OI urgency (calendar-driven, parallel to everything), and recognition that paper forward-observation (3–6 months) is the schedule long pole — not code velocity. Suggested phase structure below; ordering rationale and build-order detail in `ARCHITECTURE.md` § Build-Order Implications; per-pitfall prevention phases in `PITFALLS.md` § Pitfall-to-Phase Mapping.

### Phase 0A: Research Formalization (4–8 wks)
**Rationale:** Gates all parameter work; without frozen rules every backtest is an anecdote.
**Delivers:** Candidate families scoped as hypotheses, exact entry/SL/TP/cost/execution assumptions, parameter-registry schema, golden-fixture format, acceptance gates, anti-overfitting constraints; Core Docs v0.3 contradiction list resolved (see Open Questions).
**Addresses:** Validation gates, experiment registry, kill-gate definition (FEATURES.md MVP/gates).
**Avoids:** Pitfalls 1/2/4/5/6/16/17 (look-ahead, repaint, isolated optimum, holdout peek, costs-late, notebook-as-canonical, spec bypass).
**Uses:** Pydantic registry schema, pytest golden harness, VectorBT exploratory-only.

### Phase 0B: Data Foundation Bootstrap (1–2 wks bootstrap + continuous)
**Rationale:** Highest calendar urgency — OI snapshots are irrecoverable; everything downstream needs candles/metadata.
**Delivers:** Project scaffold (pyproject/uv/pytest+Ruff+mypy/Docker+Compose PG17), 1m/1H/4H backfill, OI collector live from day one, funding + exchangeInfo/symbol-metadata pipeline, quality checks (dedup/OHLC-sanity/sequence/gap), warm-up gate, backup/restore smoke test.
**Addresses:** Market-data ingestion, OI/funding collectors, symbol metadata, backup drill.
**Avoids:** Pitfalls 3/8/13/14 (intrabar data absence, hard-coded filters, stale-data/warm-up, OI window).
**Uses:** binance-sdk futures REST/WS, Parquet+DuckDB, PostgreSQL 17, Alembic baseline.

### Phase 1: Domain + Parameter Registry + Fixture Harness
**Rationale:** Reproducibility harness before families — new behavior must be expressible as a versioned set before it exists.
**Delivers:** `domain/` enums/state machines (Signal≠Order≠Position≠Approval), immutable param sets with hash loader, golden fixtures (no-lookahead, candle-close timing, boundary, determinism green on stubs), CI rejects unregistered semantic changes.
**Addresses:** Deterministic ids/lineage, registry, reproducibility harness (P2→foundational).
**Avoids:** Pitfalls 2/17 (repaint, prod spec bypass).

### Phase 2: Feature + Strategy + Planner (Pure Core)
**Rationale:** Simulators consume core — core must be fixture-green first.
**Delivers:** Deterministic feature transforms (ATR/EMA/structure/zones/context), three family detectors (Trend Pullback, Breakout+Retest, Range MR — hypotheses), planner outputs with plan_hash; boundary/determinism suites passing.
**Addresses:** Feature engine, strategy engine, trade planner.
**Avoids:** Pitfalls 1/2/4/17 (look-ahead, repaint, isolated optimum, version bypass).

### Phase 3: Risk Engine
**Rationale:** Sizing/quantization must be byte-identical across modes and independently fixture-tested before any simulator trusts it.
**Delivers:** Equity×rate sizing, floor-quantization + 60% gate + QUANTIZATION_REJECT, portfolio/daily-stop states, exchange-constraint snapshots, adversarial-qty fixtures, raw/rounded/realized-risk logging.
**Addresses:** Risk engine + quantization floor.
**Avoids:** Pitfalls 6/7/8/15 (costs, round-up, hard-coded filters, revenge sizing).

### Phase 4: Backtest Simulator + Experiment Registry
**Rationale:** Canonical validation authority; VectorBT/notebooks explicitly demoted to exploration.
**Delivers:** 1m intrabar SL/TP resolver with assumption reporting, limit-fill/cost/quantization models, splits + walk-forward + baselines + bootstrap/MC uncertainty, reproducible reports with full identity tuple, notebook/engine parity tests.
**Addresses:** Backtest parity engine + gates, uncertainty reporting.
**Avoids:** Pitfalls 1/3/4/5/6/7/16 (look-ahead, intrabar, isolated optimum, holdout, costs, quantization, notebook-canonical).

### Phase 5: Paper Engine — Forward Observation (3–6 mo long pole)
**Rationale:** Backtest cannot prove operational reliability; forward results feed the kill-gate decision. Schedule driver — start as early as core allows, run in parallel with hardening.
**Delivers:** Realtime WS path with warm-up/reconnect/resync, signal journal, Telegram SIMULATE/APPROVE/SKIP (no orders), system-vs-user/opportunity reports, approval-latency analytics, warm-up/gap event logging.
**Addresses:** Paper/forward engine, Telegram approval path, journal three-way base.
**Avoids:** Pitfalls 12/13/15 (duplicate approval idempotency proven here, stale-data chaos tests, daily-target culture).

### Phase 6: Approval Hardening + Reconciliation Core
**Rationale:** Must land before any live order exists; much can build during the paper soak.
**Delivers:** Idempotent expiring approvals + callback replay safety + 5× duplicate test, reconciler (local vs normal-open vs algo-open vs positions) + orphan sweeper + RECONCILIATION_REQUIRED path, SAFE_MODE + manual controls, RUNBOOK rehearsal log.
**Addresses:** Idempotent tokens, reconciliation, orphan sweeper, SAFE_MODE.
**Avoids:** Pitfalls 11/12 (orphans, duplicate orders); rehearses 9/10/13 failure modes.

### Phase 7: Live Execution Rollout (4–8 wks, smallest capital)
**Rationale:** Last, smallest, most gated — evidence earned in Phases 4–5 spends here.
**Delivers:** Order manager (LIMIT-zone entries, pending-order expiry), Algo protective exits (mode-aware, post-fill protection confirmation), partial-fill handling, live constraint snapshots + pre-placement revalidation, DAILY_STOP enforcement, smallest meaningful capital on live-5 universe.
**Addresses:** Execution manager + Algo SL/TP + user-data monitor.
**Avoids:** Pitfalls 7/8/9/10/11 (quantization live re-check, dynamic filters, Algo migration, mode misuse, orphans).

### Phase 8: Journal / Analytics Depth + Kill-Gate Operations
**Rationale:** Analytics depth after live semantics stabilize; kill-gate tracking is the institutional stop rule.
**Delivers:** MFE/MAE, system-vs-user-vs-opportunity dashboards, uncertainty reporting, live-5 vs research-universe split reporting, kill-gate tracker (3 families / 6 months → NO_TRADE valid outcome).
**Addresses:** Journal depth, kill-gate dashboard, opportunity reports.
**Avoids:** Pitfalls 5/15 (holdout discipline, profit-forcing culture).

### Phase 9+: Gated Expansion (Phase 4 in IMPLEMENTATION_PLAN) + Autonomous (Phase 5, uncommitted)
**Rationale:** Every addition measured against the frozen baseline; autonomy never on the V1 critical path.
**Delivers:** OI/funding features, 15M refinement, correlation model, new families — each a gated increment; autonomous mode stays disabled-by-default pending separate decision record + stability evidence.
**Addresses:** v1.x triggers in FEATURES.md; keeps anti-features excluded.

### Phase Ordering Rationale

- **Dependencies first:** data (0B) and protocol/registry (0A/1) before core (2/3) before simulators (4) before forward evidence (5) before order code (6/7) — simulators consume core, paper validates backtest assumptions forward, reconciliation/approval hardening precedes live enablement.
- **Calendar urgency overrides code order:** OI collector starts in 0B parallel to 0A — every delayed week permanently loses history; paper's 3–6-month observation is the long pole, so start it at the earliest viable core and harden alongside it.
- **Risk grouping:** methodology gates (look-ahead, costs, quantization, holdout) cluster in 0A/1/4 where selection happens; exchange-safety gates (Algo, modes, orphans, idempotency) cluster in 6/7 where money moves; ops gates (warm-up, SAFE_MODE, backup) start in 0B and rehearse through 5/6.
- **Pitfall avoidance by construction:** each phase's exit gate names its pitfalls' verification (prefix-invariance, ambiguous-bar share, 5× callback test, orphan-injection drill, restore drill) — see "Looks Done But Isn't" checklist in `PITFALLS.md`.

### Research Flags

Phases likely needing deeper research during planning (`--research-phase`):
- **Phase 0A:** Doc-contradiction resolution + acceptance-gate freeze — needs careful Core Docs audit (see Open Questions); sparse external precedent for kill-gate/uncertainty protocol design.
- **Phase 4 (Backtest):** 1m intrabar resolver + cost/fill model calibration — nuanced, strategy-shaping, Binance-specific fee/funding semantics.
- **Phase 7 (Live execution):** Algo-Order semantics re-verification — Binance migrates endpoints (Dec 2025 precedent); field details are MEDIUM confidence until re-checked against current official docs.

Phases with standard patterns (skip research-phase):
- **Phase 0B scaffold/collectors:** uv/PyPI-verified stack, standard PG/Parquet/DuckDB patterns, Compose packaging — well-documented.
- **Phase 1 registry/fixtures:** Pydantic/SQLAlchemy/Alembic/pytest patterns are mature and verified via Context7.
- **Phase 5 Telegram approval plumbing:** python-telegram-bot 22.x inline-keyboard + idempotency-token pattern is standard; complexity is in the safety contract (already specified), not the library.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Exchange SDK + core data/DB/web versions verified against PyPI/official docs Sep 2026; supporting-lib floors (tenacity/structlog/numpy/scipy/ruff/mypy) MEDIUM — `uv lock` resolution is the acceptance check |
| Features | HIGH | Derived directly from canonical Core Docs v0.3 pipeline, modes, risk/execution/backtest specs; 12-capability chain with dependency graph |
| Architecture | HIGH | Synthesized from canonical ARCHITECTURE/DATA_PIPELINE/DATA_MODEL/GLOSSARY/CONFIG/TESTING/RISK/EXECUTION/IMPLEMENTATION_PLAN; external endpoint facts pinned as re-verify-before-implementation |
| Pitfalls | HIGH | Grounded in repo canonical docs per pitfall section; Binance endpoint details cited from in-repo references, to be re-verified before implementation |

**Overall confidence:** HIGH

### Gaps to Address (Open Questions)

1. **Algo-Order semantics re-verification (before Phase 7):** HIGH confidence on structure (CONDITIONAL algoType, `ALGO_UPDATE.o.rm` rejection path, 200-per-symbol headroom), MEDIUM on field details (`closePosition`/`reduceOnly`/positionSide per mode, exact Algo REST/WS schemas). Handle: dedicated API re-verification task against current developers.binance.com + changelog before wiring order paths; never hard-code from memory.
2. **Numeric thresholds TBD (research placeholders, not decisions):** Max 2 open / 1.0% aggregate, conservative correlated-cluster cap, 60% quantization floor, 3–6 mo paper window, 10–15 research universe — all marked as starting assumptions in Core Docs. Handle: Phase 0A freezes them as explicit hypotheses with rationale; validation gates (neighborhood stability, walk-forward, live-5 slice) confirm or revise.
3. **Core Docs v0.3 contradictions for Phase 0A audit (resolve, don't silently fix):** SystemMode LIVE_AUTONOMOUS vs LIVE_AUTONOMOUS_DISABLED + SAFE_MODE scoping; SIGNAL_AND_ALERTS alert-states mixing execution states into SignalStatus; EXECUTION_SPEC §3 APPROVED vs GLOSSARY OrderStatus; Bangkok vs Ho_Chi_Minh timezone naming; RESEARCH §12 non-canonical status names; duplicate section numbers (BACKTEST_SPEC §11×2/§13, DATA_PIPELINE §8/§9 repeat, TRADINGVIEW §7 gap, SECURITY §10 gap, RESEARCH §13/§14 restart). Handle: Phase 0A produces the explicit contradiction/gap list as a PROJECT.md Active requirement before spec freeze.
4. **Strategy V1 family TBD (D012):** No premature winner — Trend Pullback vs Breakout+Retest vs Range MR decided by frozen-protocol evidence. Handle: 0A scopes all three as hypotheses; kill gate (3 families / 6 months, NO_TRADE valid) bounds the search.
5. **Supporting-library version floors (MEDIUM):** tenacity/structlog/NumPy/SciPy/pandas/Ruff/mypy numbers from training knowledge + convention. Handle: Phase-0B `uv lock` resolution + CI green is the acceptance check; pin majors, let the resolver arbitrate.

## Sources

### Primary (HIGH confidence)
- Canonical Core Docs v0.3 (`docs/`): 00_PRODUCT_SCOPE, 01_ENGINEERING_PRINCIPLES, DECISIONS D001–D021, GLOSSARY, SOURCES, TECHNOLOGY_STACK, ARCHITECTURE, DATA_PIPELINE, DATA_MODEL, CONFIGURATION, TESTING_STRATEGY, TRADING (SIGNAL_AND_ALERTS, RISK_MANAGEMENT, EXECUTION_SPEC), BACKTEST (BACKTEST_SPEC, METRICS), INTEGRATION (BINANCE, TELEGRAM, TRADINGVIEW), OPERATIONS (RUNBOOK, SECURITY_AND_OPERATIONS), IMPLEMENTATION_PLAN — project authority for features/architecture/pitfalls
- PyPI + GitHub releases Sep 2026: `binance-sdk-derivatives-trading-usds-futures` v17.3.1, `binance-sdk-algo` 3.4.0, archived `binance-connector`/`binance-futures-connector` (Apr 2026), polars 1.44.1, duckdb 1.5.5, fastapi 0.141.1, uvicorn 0.52.4, python-telegram-bot 22.8, psycopg 3.3.5, httpx 0.28.1, alembic 1.19.1, pytest 9 — stack versions
- Context7 docs sampled for SQLAlchemy-async (engine + psycopg_pool), Polars, DuckDB, psycopg3, FastAPI, pytest, Pydantic — integration patterns
- Binance docs as cited in-repo (structure HIGH / field detail MEDIUM): `/fapi/v1/algoOrder` new/query/cancel, Future Algo REST, Dec-2025 conditional→Algo migration + `ALGO_UPDATE.o.rm`, exchangeInfo filters, WS streams 24h lifetime, OI ~30-day window

### Secondary (MEDIUM confidence)
- Supporting-library floors (tenacity/structlog/NumPy/SciPy/pandas/Ruff/mypy) from training knowledge + ecosystem convention — validated at `uv lock`
- Binance field-level details (closePosition constraints, position-mode branching, 200-conditional limit) — re-verify vs current official docs at implementation
- TradingView strategy/webhook support pages as cited in FEATURES.md — re-verify if webhook adapter activates

### Tertiary (LOW confidence)
- None — no load-bearing claim rests on a single unverified source; research placeholders are explicitly flagged above as Open Questions, not findings.

---
*Research completed: 2026-09-19*
*Ready for roadmap: yes*
