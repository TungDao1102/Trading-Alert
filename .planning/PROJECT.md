# Deterministic Binance Futures Research & Semi-Automated Execution System

## What This Is

A deterministic, reproducible Binance Futures trading research and semi-automated execution system for a full-time worker with $500–1,000 research capital. It detects a small number of well-defined setups on 4H/1H, generates complete trade plans (Entry/SL/TP/risk/quantity) deterministically, notifies via Telegram, and only places orders after explicit human APPROVE — never auto-trading in V1.

## Core Value

Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Core Docs v0.3 audit complete with contradictions/gaps explicitly listed (no silent fixes)
- [ ] Candidate strategy families (Trend Pullback, Breakout+Retest, Range Mean-Reversion) researched as hypotheses with deterministic alternatives per concept
- [ ] Strategy V1 research protocol frozen (dataset splits, cost model, execution simulation, acceptance gates) before parameter work
- [ ] Phase-0 data foundation running (1m/1H/4H candles, funding, self-collected OI snapshots, symbol metadata) with backup/restore smoke test
- [ ] Backtest engine reproduces live logic (closed-candle, no-lookahead, warm-up, 1m intrabar resolution, fees/funding/slippage, quantization) with baseline comparisons
- [ ] Realtime paper engine (WS market data, warm-up/reconnect, planner, risk, journal, Telegram SIMULATE/APPROVE/SKIP) with forward evidence
- [ ] Human-approved live execution (idempotent approval, LIMIT-zone entry, Algo-Order protective exits, reconciliation, orphan sweeper, SAFE_MODE, RUNBOOK rehearsed)
- [ ] Journal/analytics separates system performance vs user-executed vs opportunity (skipped/expired) with MFE/MAE and uncertainty reporting
- [ ] NO_TRADE remains a valid outcome under the 3-families / 6-months kill gate (D013)

### Out of Scope

- Fully autonomous live trading (LIVE_AUTONOMOUS) — future only, disabled by default, requires separate evidence/gates — why: user wants explicit control and evidence first
- AI/LLM price prediction or LLM-generated Entry/SL/TP/size — why: violates determinism and D001
- News-driven discretion, order-book ML, reinforcement learning, HFT/scalping — why: incompatible with limited screen time and research budget
- Forced daily profit target / $X-per-day optimization — why: forces overtrading; zero-trade days are valid
- Kafka/RabbitMQ/K8s/large microservice topology, Rust rewrite, NautilusTrader as mandatory foundation — why: no measured bottleneck; keep strategy contracts under project control
- 5M as required V1 timing dependency — why: short-TTL signals mismatch full-time availability (D006)

## Context

- Existing source of truth: `docs/` Core Docs v0.3 (2026-09-19) — README, 00_PRODUCT_SCOPE, 01_ENGINEERING_PRINCIPLES, DECISIONS (D001–D021), GLOSSARY (canonical enums), SOURCES, TECHNOLOGY_STACK (Python 3.13, uv, Parquet+DuckDB / PostgreSQL), TRADING_STRATEGY_RESEARCH (living draft v0.1, Vietnamese/English), TRADING_STRATEGY_SPEC (TEMPLATE/NOT FROZEN), ARCHITECTURE, DATA_PIPELINE, RISK_MANAGEMENT (0.5% baseline), EXECUTION_SPEC (Algo-Order migration), SIGNAL_AND_ALERTS, BACKTEST_SPEC, METRICS, DATA_MODEL (canonical), CONFIGURATION (parameter registry), TESTING_STRATEGY (golden fixtures), BINANCE/TELEGRAM/TRADINGVIEW integrations, SECURITY_AND_OPERATIONS, RUNBOOK, IMPLEMENTATION_PLAN (15–24 mo path, Phase 0A/0B→5), AGENT_INSTRUCTIONS.
- Research capital $500–1,000 treated as research capital, not living-expense stream; illustrative envelope ($800 × 0.5% × 15 × 0.175R ≈ $10.50/mo) is arithmetic only, not a forecast.
- Canonical pipeline: Market Data → Feature Engine → Deterministic Strategy Engine → Trade Plan → Risk Engine → Human Approval → Execution → Position/Order Events → Journal → Research/Performance. Signal ≠ TradePlan ≠ Approval ≠ Order ≠ Fill ≠ Position.
- V1 live universe (research, not performance claim): BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT. Research may use 10–15 liquid symbols but must report live-universe slice separately.
- Timeframes: 4H regime/context, 1H setup; 15M entry-refinement optional; 1M for execution simulation only. Closed-candle decisions; UTC internally, Asia/Ho_Chi_Minh presentation.
- Known doc inconsistencies to resolve (not silently): SystemMode LIVE_AUTONOMOUS vs LIVE_AUTONOMOUS_DISABLED + missing SAFE_MODE in scope modes; SIGNAL_AND_ALERTS alert-states mix execution states into SignalStatus; EXECUTION_SPEC order lifecycle APPROVED vs GLOSSARY OrderStatus; Bangkok vs Ho_Chi_Minh timezone naming; RESEARCH §12 non-canonical status names; duplicate section numbers (BACKTEST_SPEC §11×2/§13, DATA_PIPELINE §8/§9 repeat, TRADINGVIEW §7 gap, SECURITY §10 gap, RESEARCH §13/§14 restart).
- Greenfield code: no `src/`, `pyproject.toml`, or DB yet — intentional (research/spec/code separation; do not code before spec freeze).

## Constraints

- **Determinism**: same market snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs
- **No-AI core**: LLM may assist code/docs/tests/explanations only; must never decide direction/entry/SL/TP/size/risk/parameters/signal-validity
- **Exchange authority**: Binance is canonical for orders/fills/positions/PnL/fees/conditional orders; user-data WS preferred realtime; dynamic exchangeInfo (stepSize/tick/notional), Algo-Order endpoints, position-mode detection, 200-conditional-order headroom — all re-verified against current official docs before implementation, never hard-coded from memory
- **Quantization**: floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject → NO_TRADE preferred over round-up; identical logic backtest/paper/live
- **Approval safety**: explicit, auditable, idempotent, expiring; at-least-once Telegram callbacks replay to existing state; no auto-approve on notification failure; stale/invalid plans unapprovable
- **Fail closed**: uncertain data/connection/account/risk → NO_TRADE, no new orders; SAFE_MODE blocks entries while monitoring/reconciliation continues
- **Tech stack**: Python 3.13, asyncio, official Binance Python connector (3.10+) behind adapters, FastAPI only for webhook/health edge, PostgreSQL (operational) + Parquet/DuckDB (research), Polars/pandas/NumPy/SciPy, VectorBT exploratory-only, pytest+Ruff+mypy, Docker, Decimal/tick arithmetic for exchange-sensitive values
- **Timeline**: one part-time developer (evenings/weekends); Phase 0A 4–8 wks, 0B 1–2 wks bootstrap + continuous, Phase 1 backtest 6–10 wks, Phase 2 paper 3–6 mo forward observation, Phase 3 live rollout 4–8 wks; overall ~15–24 mo to first cautious live order

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| No AI/LLM in trading decision core (D001) | Deterministic, reproducible, backtestable; avoids stale-context subjective predictions | — Pending |
| Binance canonical execution/data source (D002); TradingView optional adapter (D003) | Trading occurs on Binance; Pine/visual/webhook useful for cross-check without coupling execution | — Pending |
| Human approval before early live execution (D004) | User unavailable continuously; explicit control | — Pending |
| 4H + 1H primary; 15M/5M optional, not V1 core (D005/D006) | Fits limited screen time; short-TTL mismatched | — Pending |
| Signal ≠ plan ≠ order ≠ position (D007); canonical data model (D014); parameter registry (D015); GLOSSARY enums (D016) | Prevents coupling; supports system-vs-user analytics; reproducibility | — Pending |
| Backtest before paper/live (D008); data collection Phase 0 (D017); OI self-collect day one (D009) | OI history (30-day API window) irrecoverable; avoid live-sampling historical questions | — Pending |
| No fixed daily profit target (D010); NO_TRADE valid; kill gate 3 families + 6 months (D013) | Avoids forced trading; stops endless complexity | — Pending |
| V1 likely limit-zone execution for swing setups (D011, provisional) | Better fit for limited availability; needs expiry/invalidation | — Pending |
| Python 3.13 + uv + Parquet/DuckDB + PostgreSQL (D018–D021) | Research-heavy low-frequency workload; separates analytical vs transactional storage | — Pending |
| Strategy V1 family TBD (D012) | Research must decide; no premature winner | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-19 after initialization*
