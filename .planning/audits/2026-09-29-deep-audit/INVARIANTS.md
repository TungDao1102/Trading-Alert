# INVARIANTS — Business and System Invariants (audit input)

> Snapshot: `63ca176` (`C:\Users\admin\Music\project-audit\2026-09-29_63ca176\snapshot`)
> Extracted: 2026-09-29. Extraction stage of the read-only forensic audit (see `AUDIT_CHARTER.md` §3.3).
> Sources are limited to authoritative project documents: `AGENTS.md`, `docs/**`, `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`. `params/**/*.toml` are cited only as evidence of configured values.
> No invariant here comes from `src/`. The "Affected entities/modules" lines name likely code locations taken from the snapshot file listing, so lanes know where to look. They are not claims about behavior.
> Line numbers refer to the snapshot files, and `§` refers to the document's own section numbering.
> Ambiguities are listed as `AMB-xxx` at the end. None of them is resolved here.
> **Scope update (coordinator):** `docs/` are AI-generated and are treated as *documented intent*, not ground truth. Every INV block therefore carries a `Domain soundness` flag (OK / QUESTIONABLE / UNKNOWN). The flag rests only on general trading and Binance-futures knowledge and was not verified against live Binance docs. It is a pointer for later lanes to investigate, not a verdict.

---

## Source Authority Notes

**DOC_STATUS precedence** (`docs/DOC_STATUS.md`):

1. **Stable / canonical:** `00_PRODUCT_SCOPE`, `01_ENGINEERING_PRINCIPLES`, `GLOSSARY` (the only source of truth for enums and rejection reasons, D016), `data/DATA_MODEL` (the only persistence contract, D014), `configuration/CONFIGURATION` (the parameter registry, D015), `testing/TESTING_STRATEGY`, `DECISIONS`, `TECHNOLOGY_STACK`, and `research/RESEARCH_PROTOCOL`. The research protocol is FROZEN v1.0.1 (D029, D030), and three witnesses must agree: its header, a DECISIONS row, and the DOC_STATUS entry.
2. **Living research:** `research/TRADING_STRATEGY_RESEARCH.md`. It is a draft, and a frozen protocol outranks it (protocol §0 "living-doc firewall"). D025 shows the precedence rule "engineering principles outrank research notes".
3. **Blocked until strategy freeze:** `strategy/TRADING_STRATEGY_SPEC.md` is a TEMPLATE and NOT FROZEN, with every rule `TBD`. It "becomes implementation-authoritative only after the research gates pass". Its §13 acceptance status is all `NO`, including "Approved for live human-approved trading: NO".
4. **Baseline architecture/specification:** `ARCHITECTURE`, `DATA_PIPELINE`, `BACKTEST_SPEC`, `METRICS`, `RISK_MANAGEMENT` (README: "Baseline + parameters TBD"), `EXECUTION_SPEC` (README: "Binance details verified before implementation"), and `SIGNAL_AND_ALERTS`.
5. **Integrations / Operations / Implementation:** `BINANCE` ("Current-data dependent"), `TRADINGVIEW` ("Optional"), `TELEGRAM`, `SECURITY_AND_OPERATIONS`, `RUNBOOK` ("Operational"), `IMPLEMENTATION_PLAN`, and `AGENT_INSTRUCTIONS`.
6. **Not indexed by DOC_STATUS:** `AGENTS.md` (repo root), `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, and `.planning/ROADMAP.md`.
   - These are derived planning artifacts. PROJECT.md's Constraints block is mirrored verbatim into AGENTS.md.
   - `RESEARCH_PROTOCOL.md` §2 and §6 cite "`docs/AGENTS.md` Constraints (canonical)", but that path does not exist; the file is at the repo root. See AMB-001.
   - ROADMAP phases 11–17 are promoted backlog items. They state rules (fee units, equity source, leverage/liquidation guard, margin check, live-price check, notification amounts, quote asset) that have **no counterpart in any canonical doc**. Those invariants are tagged `[PLANNED, not yet canonical]`.
7. **Phase-local decisions:** "Phase 5 D-02/D-03/D-05" and "Phase 10 D-03" are cited inside GLOSSARY §8.1, §8.2 and §9, so their enum values are canonical through GLOSSARY. Their full text lives in `.planning/phases/*` and was not used as an authority here.
8. **Documented precedence mechanisms:** DECISIONS rows (D022–D030) are the mechanism for resolving doc contradictions (RSCH-03). GLOSSARY wins on enums (D016), DATA_MODEL on persistence (D014), and CONFIGURATION on parameters (D015).
9. **Precedence the docs do not define:** the docs do not rank canonical docs against `.planning` requirements or `AGENTS.md`. See AMB-001.

---

## A. Determinism, no-lookahead, and prefix invariance

### INV-001 — Same inputs produce the same decision
- **Source:**
  - `docs/01_ENGINEERING_PRINCIPLES.md` §1 (L5–16): "same inputs + same version = same decision"
  - `AGENTS.md` L13
  - `.planning/PROJECT.md` L50
- **Exact rule:** Given the same market data snapshot, account state, strategy version and configuration (parameter set), the strategy engine produces the same result.
- **Scope:** all
- **Affected entities/modules:** `src/core/strategy.py`, `src/core/planner.py`, `src/core/features.py`, `src/risk/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - There are no hidden inputs: wall-clock `now()`, randomness, env vars, dict/set iteration order, or locale inside `core/` and `risk/`.
  - Account state is an explicit input.
  - Every configuration value comes from the registered parameter set.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-002 — Canonical decision output is byte-equivalent
- **Source:**
  - `docs/testing/TESTING_STRATEGY.md` §6 (L80–91): "must produce byte-equivalent canonical decision output"
  - `AGENTS.md` L13
- **Exact rule:** The same market data, strategyVersion, parameterSet and account state serialize to a byte-identical canonical decision output.
- **Scope:** all
- **Affected entities/modules:** `src/domain/canonical.py`, `src/core/*`, `src/risk/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - A canonical serializer exists: sorted keys, fixed Decimal formatting, no float repr.
  - Tests compare bytes, not approximate values.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-003 — No-lookahead prefix invariance
- **Source:**
  - `docs/testing/TESTING_STRATEGY.md` §3 (L39–51): "The output for all events at or before T must be identical. This is a mandatory invariant."
  - `.planning/REQUIREMENTS.md` DOMN-03
  - ROADMAP Phase 4 SC2
- **Exact rule:** Running on a candle prefix ending at T, and then on the same prefix with arbitrary candles appended after T, must produce identical output for all events at or before T.
- **Scope:** all (backtest, paper, live strategy evaluation)
- **Affected entities/modules:** `src/core/features.py`, `src/core/strategy.py`, `src/backtest/simulator.py`, `src/paper/loop.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - A prefix-invariance test exists for every family (trend-pullback, breakout-retest, range-mr).
  - Features never index forward (for example centered pivots or `shift(-k)`).
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-004 — Closed-candle rule
- **Source:**
  - `docs/backtest/BACKTEST_SPEC.md` §3 (L18–22)
  - `docs/research/RESEARCH_PROTOCOL.md` §3 "Closed-candle rule"
  - `01_ENGINEERING_PRINCIPLES.md` §6
  - `integration/BINANCE.md` §4
  - `DATA_PIPELINE.md` §4
- **Exact rule:**
  - Strategy decisions use only information available by the source candle close.
  - No future candle data, future swing confirmation, or future intrabar outcome may leak into a decision.
  - An unfinished candle may not declare a signal.
- **Scope:** all
- **Affected entities/modules:** `src/core/*`, `src/adapters/paper_ws.py` (kline `x`/closed flag), `src/paper/loop.py`, `src/backtest/simulator.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The WS path acts only on closed klines.
  - Swing/pivot detection requires its right-side bars to be already closed at decision time.
  - The backtest never reads bar T+1 when deciding at T.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-005 — Live decisions require a closed kline; preview only when explicitly labelled
- **Source:**
  - `docs/testing/TESTING_STRATEGY.md` §4 (L53–66): "kline closed = required"
  - `SIGNAL_AND_ALERTS.md` §6 (L113)
- **Exact rule:**
  - An unfinished candle may be inspected only as explicitly classified preview data.
  - No alert is sent for an unfinished strategy candle unless it is designated an informational preview.
  - A signal is absent before close and appears exactly once after close.
- **Scope:** paper, live
- **Affected entities/modules:** `src/paper/loop.py`, `src/adapters/paper_ws.py`, `src/paper/notify.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - A test shows the signal is absent before close.
  - A test shows the signal is emitted exactly once after close, including on WS duplicate or replayed close events.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-006 — Warm-up gating
- **Source:**
  - `docs/architecture/DATA_PIPELINE.md` §5 (L50–66)
  - `RESEARCH_PROTOCOL.md` §3
  - `REQUIREMENTS.md` STRAT-01
  - ROADMAP Phase 4 SC1
  - `TESTING_STRATEGY.md` §5 "insufficient warm-up history"
- **Exact rule:**
  - Indicators that need long history (for example EMA200-4H) are flagged invalid until sufficient history exists.
  - Strategy evaluation must not use invalid features.
  - Startup sequence: REST history → validate continuity → seed → attach WS → verify latest closed candle.
- **Scope:** all
- **Affected entities/modules:** `src/core/features.py`, `src/paper/supervisor.py`, `src/paper/resync.py`
- **Expected state transitions:** feature `INVALID → VALID` only when history is sufficient
- **Verification targets:**
  - Feature validity flags exist.
  - The strategy returns NO_TRADE (not a setup) when warm-up is insufficient.
  - A boundary test exists at exactly the warm-up length.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-007 — Strategy is a pure function
- **Source:**
  - `REQUIREMENTS.md` STRAT-02: "Strategy engine is a pure function (market snapshot + account state + strategy version + config → NO_TRADE or SETUP)"
  - `ARCHITECTURE.md` §2 "Strategy Engine … must not call Binance trading endpoints"
  - `AGENT_INSTRUCTIONS.md` §11 "free of network/database side effects"
- **Exact rule:** The strategy engine outputs NO_TRADE or SETUP only. It performs no network, DB, Telegram or order calls.
- **Scope:** all
- **Affected entities/modules:** `src/core/strategy.py`, `src/core/features.py`, `src/core/planner.py`
- **Expected state transitions:** n/a
- **Verification targets:** `core/` has no imports of adapters, db, httpx, the binance SDK, telegram or asyncio I/O.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-008 — Domain boundary: no framework or SDK types in the strategy domain
- **Source:**
  - `docs/TECHNOLOGY_STACK.md` §4–5 (L67, L69–85)
  - `DATA_PIPELINE.md` §14
  - `BINANCE.md` §2
  - `TRADINGVIEW.md` §7
  - `AGENT_INSTRUCTIONS.md` §11
- **Exact rule:**
  - The strategy does not depend on pandas, Polars, DuckDB, Binance SDK classes, FastAPI or PostgreSQL/ORM models.
  - SDK response models and raw JSON never leak into the domain.
  - Webhook payloads are normalized to project types first.
- **Scope:** all
- **Affected entities/modules:** `src/core/*`, `src/domain/*`, `src/risk/*`, `src/adapters/*`, `src/db/models.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Check import graph: `core`/`domain`/`risk` import none of `polars`, `pandas`, `duckdb`, `binance*`, `fastapi`, `sqlalchemy`.
  - ORM models are not used as domain objects (mappers exist).
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-009 — Forbidden dependency edges
- **Source:** `docs/architecture/ARCHITECTURE.md` §3 (L117–128)
- **Exact rule:** These edges are forbidden:
  - Strategy → Telegram
  - Strategy → Binance order API
  - LLM → Strategy decision
  - UI → direct Binance order API
- **Scope:** all
- **Affected entities/modules:** `src/core/*`, `src/adapters/telegram_*`, `src/adapters/binance_usdm.py`
- **Expected state transitions:** n/a
- **Verification targets:** Static import check.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-010 — Only the Execution Manager calls live trading endpoints
- **Source:** `docs/architecture/ARCHITECTURE.md` §2 "Execution Manager — Only component allowed to call live trading endpoints"
- **Exact rule:** Order placement, cancellation and modification calls originate only from the execution component.
- **Scope:** live
- **Affected entities/modules:** `src/execution/manager.py`, `src/execution/placement.py`, `src/reconcile/sweeper.py`, `src/adapters/binance_usdm.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - List every caller of `new_order`, `algo_order` and `cancel` adapter methods.
  - Flag any caller outside execution. For example, the sweeper cancelling orders is a potential boundary question.
- **Ambiguity:** AMB-024
- **Domain soundness:** OK

### INV-011 — Decimal/tick arithmetic for exchange-sensitive values
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` Python §L100
  - `TECHNOLOGY_STACK.md` §3
  - `DATA_MODEL.md` §5 "do not use binary floating point for persisted financial calculations"
  - `AGENTS.md` L153
- **Exact rule:**
  - Prices, quantities, notional, risk and fees that can gate an order use `Decimal` or integer tick/step arithmetic.
  - Floats are allowed only in statistical/feature code that never gates an order.
  - Persisted monetary, price and quantity values use decimal-safe types.
- **Scope:** all
- **Affected entities/modules:** `src/risk/*`, `src/execution/*`, `src/backtest/costs.py`, `src/core/_decimal.py`, `src/db/models.py` (Numeric columns)
- **Expected state transitions:** n/a
- **Verification targets:**
  - `float(` and float literals do not appear in the sizing, quantization, order or cost paths.
  - DB columns are Numeric, not Float.
  - TOML floats are converted to Decimal via `str`, not via a binary float.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-012 — Same strategy implementation in every mode
- **Source:**
  - `docs/README.md` L93
  - `TECHNOLOGY_STACK.md` §5
  - `01_ENGINEERING_PRINCIPLES.md` L104–105
  - `IMPLEMENTATION_PLAN.md` Python notes
  - `BACKTEST_SPEC.md` §13
- **Exact rule:**
  - The same deterministic strategy code runs in backtest, paper and live.
  - Notebooks and research call the library and do not duplicate it.
  - Final validation uses the canonical project engine; VectorBT and similar tools are exploratory only.
- **Scope:** all
- **Affected entities/modules:** `src/backtest/simulator.py`, `src/paper/loop.py`, `src/execution/manager.py`, `src/core/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Backtest and paper call the same `evaluate`/planner functions.
  - A parity test exists (ROADMAP Phase 7 "backtest parity gate").
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-013 — Deterministic, immutable SignalId
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` §7 (L69–77)
  - `SIGNAL_AND_ALERTS.md` §3 (L47–61)
  - `DATA_MODEL.md` §2.3 "signal_id is deterministic and unique"
  - `STRAT-02`
- **Exact rule:**
  - SignalId = hash(StrategyVersion, Symbol, SourceTimeframe, SourceCandleCloseUtc, SetupType).
  - A restart cannot duplicate a signal or alert.
  - The DB enforces uniqueness.
- **Scope:** all
- **Affected entities/modules:** `src/domain/ids.py`, `src/domain/signal.py`, `src/db/models.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Hash inputs are exactly the listed fields (or a documented superset).
  - A unique constraint exists on `signal_id`.
  - Re-running after restart does not insert a duplicate.
- **Ambiguity:** AMB-020
- **Domain soundness:** QUESTIONABLE (the hash omits strategy_id, parameterSetHash and direction. Families and baselines share version "v2.0.0", so two parameter sets could get the same SignalId on the same candle; see AMB-020)

### INV-014 — No repeated alert for the same SignalId
- **Source:** `docs/trading/SIGNAL_AND_ALERTS.md` §6 (L115): "No repeated alert for the same signal ID."
- **Exact rule:** At most one alert (notification) per SignalId, including across restarts and WS replays.
- **Scope:** paper, live
- **Affected entities/modules:** `src/paper/notify.py`, `src/adapters/telegram_notify.py`, `src/paper/journal.py`
- **Expected state transitions:** SignalStatus `DETECTED → NOTIFIED` happens once
- **Verification targets:**
  - The notify path checks persisted status or an idempotency key before sending.
  - A crash between send and persist is handled.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-015 — UTC internally; Asia/Ho_Chi_Minh only in presentation
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` §8 (L79–81)
  - `DATA_MODEL.md` §5
  - `DATA_PIPELINE.md` §7
  - D025
  - `TRADING_STRATEGY_RESEARCH.md` §9.3
- **Exact rule:**
  - All persisted timestamps are UTC.
  - Conversion to `Asia/Ho_Chi_Minh` happens only for presentation, via `zoneinfo` (and the `tzdata` wheel on Windows), never via a hard-coded +7 offset.
- **Scope:** all
- **Affected entities/modules:** `src/db/models.py` (timezone-aware columns), `src/adapters/telegram_notify.py`, `src/paper/notify.py`, `src/analytics/render*.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - There are no naive datetimes in the domain and no `timedelta(hours=7)`.
  - Every `datetime.now()` call is given an explicit UTC timezone.
- **Ambiguity:** AMB-012 (day boundary)
- **Domain soundness:** OK

---

## B. No-AI decision path

### INV-016 — No AI/LLM in decisions
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` §2 (L18–31)
  - D001
  - `AGENT_INSTRUCTIONS.md` §2
  - `TRADING_STRATEGY_SPEC.md` §11
  - `AGENTS.md` L14
- **Exact rule:**
  - AI/LLM must not decide or modify direction, entry, SL, TP, size, risk limits/state, parameters or signal validity.
  - AI may be used only for code, docs, tests and explanatory text.
- **Scope:** all
- **Affected entities/modules:** entire `src/`
- **Expected state transitions:** n/a
- **Verification targets:**
  - There are no LLM client imports (anthropic, openai and similar) or HTTP calls to LLM endpoints in `src/`.
  - No "subjective classifier" path exists.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## C. Domain model, enums, and state machines

### INV-017 — Seven separate entities
- **Source:**
  - `DATA_MODEL.md` §1 (L7–25): "Do not collapse these entities into one row or one status enum"
  - D007
  - D014
  - DOMN-01
- **Exact rule:**
  - Signal, TradePlan, Approval, Order, Fill, Position and JournalEvent (plus Trade) are separate entities, each with its own table and state.
  - `SignalStatus ≠ OrderStatus ≠ PositionStatus ≠ ApprovalAction`.
- **Scope:** all
- **Affected entities/modules:** `src/domain/*`, `src/db/models.py`, migrations `0002`
- **Expected state transitions:** see INV-020..026
- **Verification targets:**
  - Separate tables and enums exist.
  - There is no shared status column.
  - `trades` exists as a separate table (DATA_MODEL §2.6).
- **Ambiguity:** AMB-026
- **Domain soundness:** OK

### INV-018 — Canonical enums only; no synonyms
- **Source:**
  - `GLOSSARY.md` (whole doc; L179 "Do not create synonyms")
  - D016
  - `AGENT_INSTRUCTIONS.md` §9
- **Exact rule:** Status, action and rejection-reason values are exactly the GLOSSARY lists. No module defines alternative spellings or extra values.
- **Scope:** all
- **Affected entities/modules:** `src/domain/enums.py`, `src/db/models.py` (DB enums/check constraints), `src/risk/types.py`, `src/analytics/*`
- **Expected state transitions:** n/a
- **Verification targets:** Diff the code enums against GLOSSARY §2–§9. This includes the rejection reasons, DailyState and KillGateState.
- **Ambiguity:** AMB-008
- **Domain soundness:** OK

### INV-019 — Explicit state machines; no state inferred from nullable columns
- **Source:**
  - `ARCHITECTURE.md` §5
  - `DATA_MODEL.md` §5 "State transitions must be validated in application code"
  - DOMN-01
  - `TECHNOLOGY_STACK.md` §3 "explicit state machines"
- **Exact rule:**
  - Signal, TradePlan, Order, Trade and Position each have an explicit lifecycle with validated transitions.
  - State is never derived only from nullable columns.
- **Scope:** all
- **Affected entities/modules:** `src/domain/*.py`
- **Expected state transitions:** per enum
- **Verification targets:**
  - A transition table or validator exists per entity.
  - Invalid transitions raise.
  - No code computes status as `filled_at is not None` and similar.
- **Ambiguity:** AMB-009
- **Domain soundness:** OK

### INV-020 — SignalStatus values
- **Source:**
  - `GLOSSARY.md` §2 (L37–50)
  - `SIGNAL_AND_ALERTS.md` §4
  - D023
- **Exact rule:**
  - SignalStatus ∈ {DETECTED, NOTIFIED, VIEWED, APPROVED, SKIPPED_USER, SKIPPED_BUSY, EXPIRED, INVALIDATED}.
  - Execution lifecycle states do not belong in SignalStatus.
- **Scope:** all
- **Affected entities/modules:** `src/domain/signal.py`, `src/domain/enums.py`
- **Expected state transitions:** `DETECTED → NOTIFIED → (VIEWED) → APPROVED | SKIPPED_USER | SKIPPED_BUSY | EXPIRED | INVALIDATED`. The full graph is not specified (AMB-009).
- **Verification targets:**
  - `EXPIRED → APPROVED` is rejected (TESTING_STRATEGY §8).
  - No order or fill states are mixed into this enum.
- **Ambiguity:** AMB-009
- **Domain soundness:** OK

### INV-021 — Signal APPROVED is not TradePlan APPROVED; order placement reads the plan status
- **Source:**
  - `GLOSSARY.md` §2.1 (L52–54)
  - D028
  - `DATA_MODEL.md` §3 (L340)
  - `SIGNAL_AND_ALERTS.md` §1 (L19)
- **Exact rule:**
  - Order placement reads `TradePlan.status`, never `Signal.status`.
  - Ordering: Signal APPROVED → TradePlan APPROVED → Order PLANNED.
  - Signal APPROVED never implies that Binance accepted an order.
- **Scope:** paper, live
- **Affected entities/modules:** `src/execution/manager.py`, `src/execution/gates.py`, `src/approval/*`, `src/domain/trade_plan.py`
- **Expected state transitions:** `Signal APPROVED → TradePlan APPROVED → Order PLANNED`
- **Verification targets:**
  - The execution gate checks `TradePlanStatus.APPROVED`.
  - There is no code path from Signal APPROVED straight to order submission.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-022 — TradePlanStatus values
- **Source:** `GLOSSARY.md` §3 (L56–65)
- **Exact rule:** TradePlanStatus ∈ {READY, APPROVAL_PENDING, APPROVED, EXPIRED, INVALIDATED, SUPERSEDED}.
- **Scope:** all
- **Affected entities/modules:** `src/domain/trade_plan.py`
- **Expected state transitions:**
  - `READY → APPROVAL_PENDING → APPROVED`
  - `→ EXPIRED | INVALIDATED | SUPERSEDED` (graph unspecified)
- **Verification targets:**
  - Terminal states cannot become APPROVED.
  - The code has no CANCELED plan state (compare AMB-010).
- **Ambiguity:** AMB-009, AMB-010
- **Domain soundness:** OK

### INV-023 — ApprovalAction values; VIEWED is not an action
- **Source:**
  - `GLOSSARY.md` §4 (L67–77)
  - `TELEGRAM.md` §2
- **Exact rule:** ApprovalAction ∈ {SIMULATE, APPROVE, SKIP_USER, SKIP_BUSY, CANCEL}. VIEWED is an observation state, not an action.
- **Scope:** paper, live
- **Affected entities/modules:** `src/domain/approval.py`, `src/adapters/telegram_callbacks.py`
- **Expected state transitions:** n/a
- **Verification targets:** Callback payloads map to these actions only.
- **Ambiguity:** AMB-011
- **Domain soundness:** OK

### INV-024 — OrderStatus values; the order machine has no approval state
- **Source:**
  - `GLOSSARY.md` §5 (L79–91)
  - `EXECUTION_SPEC.md` §3 (L39–53)
  - D024
  - `TESTING_STRATEGY.md` §8 (L119)
- **Exact rule:**
  - OrderStatus ∈ {PLANNED, SUBMITTING, NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED, UNKNOWN}.
  - An order enters PLANNED only after plan approval.
  - There is no APPROVED order state.
- **Scope:** live (paper where simulated)
- **Affected entities/modules:** `src/domain/order.py`, `src/execution/*`
- **Expected state transitions:**
  - `PLANNED → SUBMITTING → NEW → {PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED}`
  - REJECTED and UNKNOWN edges are unspecified (AMB-009)
- **Verification targets:**
  - The order cannot be created before plan APPROVED.
  - There is no `APPROVED` member in OrderStatus.
- **Ambiguity:** AMB-009
- **Domain soundness:** QUESTIONABLE (one OrderStatus enum for both normal and algo orders is lossy. Binance normal orders also report EXPIRED_IN_MATCH, and algo orders have their own lifecycle, e.g. TRIGGERING/TRIGGERED/FINISHED. The mapping is undocumented; re-verify)

### INV-025 — TradeStatus and PositionStatus values
- **Source:** `GLOSSARY.md` §6–§7 (L93–111)
- **Exact rule:**
  - TradeStatus ∈ {PENDING, OPEN, CLOSED, ABORTED, UNKNOWN}.
  - PositionStatus ∈ {OPEN, CLOSING, CLOSED, LIQUIDATION_REPORTED, UNKNOWN}.
  - No new protective order may be placed for a CLOSED trade unless a reconciliation workflow authorizes it.
- **Scope:** live
- **Affected entities/modules:** `src/domain/position.py`, `src/execution/fill_monitor.py`, `src/reconcile/*`
- **Expected state transitions:** CLOSED is terminal except through reconciliation (TESTING_STRATEGY §8)
- **Verification targets:**
  - A `TradeStatus CLOSED → new protective order` guard exists.
  - LIQUIDATION_REPORTED is handled.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-026 — SystemMode values; autonomous is disabled
- **Source:**
  - `GLOSSARY.md` §8 (L113–124)
  - `00_PRODUCT_SCOPE.md` §7
  - D022
- **Exact rule:**
  - SystemMode ∈ {RESEARCH, BACKTEST, PAPER, LIVE_APPROVAL, SAFE_MODE, LIVE_AUTONOMOUS_DISABLED}.
  - Autonomous live trading is disabled by default and future-only.
- **Scope:** all
- **Affected entities/modules:** `src/domain/enums.py`, `src/execution/enablement.py`, `src/reconcile/safe_mode.py`
- **Expected state transitions:** any → SAFE_MODE on trigger (INV-066)
- **Verification targets:** No code path places an order without an APPROVE (INV-043).
- **Ambiguity:** AMB-015
- **Domain soundness:** OK

### INV-027 — Relationships and integrity constraints
- **Source:**
  - `DATA_MODEL.md` §4–§5 (L342–362)
  - §2.4 L137
  - §2.8 L237–241
- **Exact rule:**
  - Relationships: Signal 1–0..1 TradePlan; TradePlan 1–N ApprovalAttempt; TradePlan 1–0..1 Trade; Trade 1–N Order; Order 1–N Fill; Trade 0..1–1 Position.
  - Foreign keys prevent orphans except where a documented NULL lifecycle applies.
  - Unique constraints protect deterministic IDs and exchange event replay (fills unique on `(order_id, exchange_trade_id)`).
  - V1 allows at most one active trade plan per signal.
- **Scope:** all
- **Affected entities/modules:** `src/db/models.py`, `src/db/alembic/versions/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The migrations declare the FKs and the unique constraints (`signal_id`, `trade_plan_id`, fill replay key, `client_order_id`, approval token hash).
  - A partial unique index enforces one active plan per signal.
- **Ambiguity:** AMB-026
- **Domain soundness:** OK

### INV-028 — Order identifiers stored independently
- **Source:** `DATA_MODEL.md` §2.7 (L214)
- **Exact rule:** `client_order_id`, `exchange_order_id` and `algo_client_id` (plus the algo id) are stored separately, because Binance uses different identifiers for normal and algo orders.
- **Scope:** live
- **Affected entities/modules:** `src/domain/order.py`, `src/db/models.py`, `src/adapters/binance_usdm.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Separate columns exist.
  - The reconciler matches algo orders by the algo id, not by the normal order id.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-029 — Journal events are append-only, not a current-state substitute
- **Source:**
  - `DATA_MODEL.md` §2.10 (L265–285)
  - §5 L362
  - D030 (KILL_GATE_EVALUATION append-only)
- **Exact rule:**
  - `journal_events` is append-only (no UPDATE or DELETE).
  - It does not replace the current-state tables.
  - It records all lifecycle events, including skipped signals (`ARCHITECTURE.md` §2 Journal).
- **Scope:** all
- **Affected entities/modules:** `src/domain/journal.py`, `src/paper/journal.py`, `src/adapters/analytics_store.py`, `src/analytics/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - There are no UPDATE or DELETE statements on `journal_events`.
  - A DB trigger or permission enforces append-only, if one is present.
  - Skipped and expired signals are journaled.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-030 — Feature snapshots are immutable and linked from the signal
- **Source:** `DATA_MODEL.md` §2.2 (L66–81)
- **Exact rule:**
  - `feature_snapshots` are immutable derived inputs.
  - The signal links to its `feature_snapshot_id`, so it can be reconstructed without recomputing from mutable configuration.
- **Scope:** paper, live, backtest
- **Affected entities/modules:** `src/domain/signal.py`, `src/db/models.py`, `src/paper/journal.py`
- **Expected state transitions:** n/a
- **Verification targets:** The signal row carries a non-null feature snapshot reference, and the snapshot is never updated.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-031 — Symbol metadata is versioned and never hard-coded
- **Source:**
  - `DATA_MODEL.md` §2.11 (L287–308)
  - DATA-03
  - `RISK_MANAGEMENT.md` §11
  - `AGENTS.md` L15, L51
- **Exact rule:**
  - Tick size, step size, min/max quantity, notional constraints and order capabilities come from live `exchangeInfo`.
  - They are stored versioned with `metadata_observed_at_utc`.
  - Strategy and risk code never hard-code symbol filters.
- **Scope:** all
- **Affected entities/modules:** `src/data/metadata.py`, `src/risk/quantization.py`, `src/execution/gates.py`
- **Expected state transitions:** n/a
- **Verification targets:** Search for literal step or tick sizes (for example `0.001`, `0.1`) in the `risk`/`execution` paths.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## D. Parameter registry and reproducibility

### INV-032 — Every decision is traceable to its identity tuple
- **Source:**
  - `CONFIGURATION.md` §4 (L64–74)
  - `RESEARCH_PROTOCOL.md` §5
  - D015
  - DOMN-02
- **Exact rule:** Every backtest, paper signal, alert, approval and live order plan is traceable to `strategyVersion`, `parameterSetId` and `parameterSetHash`.
- **Scope:** all
- **Affected entities/modules:** `src/domain/registry.py`, `src/domain/signal.py`, `src/db/models.py`, `src/backtest/experiment.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The signal rows carry the triple.
  - The approval and order rows reach it through the plan.
  - The alert text or metadata includes the identity.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-033 — A live order never uses an unregistered parameter set
- **Source:**
  - `CONFIGURATION.md` §4 L74
  - `RESEARCH_PROTOCOL.md` §5
- **Exact rule:** Live order placement requires that the plan's parameter set is registered and that its hash matches the registry.
- **Scope:** live
- **Affected entities/modules:** `src/execution/gates.py`, `src/domain/registry.py`
- **Expected state transitions:** reject → NO_TRADE
- **Verification targets:** Before placement, the execution gate verifies that the parameter set exists in the registry and that the hash matches.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-034 — Frozen parameter sets are immutable
- **Source:**
  - `CONFIGURATION.md` §5 (L76–82)
  - `RESEARCH_PROTOCOL.md` §5 "Immutability"
  - params TOML headers
- **Exact rule:**
  - A set used by a published backtest or a live-approved plan is never mutated.
  - A change requires a new parameter set, and a strategy-version bump when behavior changes materially.
  - Old sets are retained.
- **Scope:** all
- **Affected entities/modules:** `params/**`, `src/domain/registry.py`, `.github/workflows/registry-gate.yml`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The registry/CI gate detects a mutated hash for an existing id.
  - Check git history of `params/` for in-place edits.
- **Ambiguity:** AMB-021
- **Domain soundness:** OK

### INV-035 — Canonical hash normalization
- **Source:**
  - `CONFIGURATION.md` §2 L25
  - §9 (L126–132)
  - `RESEARCH_PROTOCOL.md` §5 "Loader contract"
- **Exact rule:**
  - `parameter_set_hash` is a deterministic hash over the canonical normalized document, never over the source file.
  - Keys are sorted alphabetically at each depth.
  - Numeric types are normalized to exact decimal representation.
  - Whitespace is stripped and comments are not part of the canonical form.
- **Scope:** all
- **Affected entities/modules:** `src/domain/registry.py`, `src/domain/canonical.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Reordering keys or changing comments in a TOML file does not change the hash.
  - `0.5` and `0.50` hash identically.
  - Whole-number handling is consistent (see AMB-022).
- **Ambiguity:** AMB-022
- **Domain soundness:** OK

### INV-036 — Strategy parameters are separate from runtime configuration
- **Source:** `CONFIGURATION.md` §1, §3 (L27–62): "must never silently modify strategy semantics"
- **Exact rule:**
  - Strategy parameters live only in the registry and are part of backtest identity. Examples: risk_rate, minimum_risk_utilization_after_rounding, minimum_rr and expiry.
  - Environment and runtime config (endpoints, tokens, log level, poll interval, feature flags) must never change strategy semantics.
- **Scope:** all
- **Affected entities/modules:** `src/domain/registry.py`, runtime settings modules
- **Expected state transitions:** n/a
- **Verification targets:** No env var or feature flag overrides a strategy or risk parameter at runtime.
- **Ambiguity:** AMB-023
- **Domain soundness:** OK

### INV-037 — Six-field experiment identity
- **Source:**
  - `CONFIGURATION.md` §7 (L100–113)
  - `RESEARCH_PROTOCOL.md` §5
  - `BACKTEST_SPEC.md` §11 (L136)
  - `DATA_MODEL.md` §2.12
  - BKTS-02
- **Exact rule:**
  - Every experiment record carries `experimentId`, `strategyVersion`, `parameterSetHash`, `dataSnapshotId`, `codeVersion` and `costModelHash`, plus `parameterSetId`.
  - A record missing any of these is not reproducible.
- **Scope:** backtest, research
- **Affected entities/modules:** `src/backtest/experiment.py`, `src/backtest/binding.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The record constructor fails when a field is missing.
  - `costModelHash` covers every cost field.
  - Registry and cost-model binding is enforced (ROADMAP 07.1).
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-038 — Parameter search discipline
- **Source:**
  - `CONFIGURATION.md` §8 (L115–123)
  - `RESEARCH_PROTOCOL.md` §1 R1–R6
  - §5 "Search discipline"
- **Exact rule:**
  - Sweeps run only inside ranges declared by research.
  - No search space is invented after seeing results.
  - Results are grouped by parameter region.
  - A narrow optimum is recorded as a robustness warning.
  - Parameter changes need a recorded reason (R1).
- **Scope:** research
- **Affected entities/modules:** `src/backtest/report.py`, `src/backtest/experiment.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The report includes a parameter-plateau or region analysis (BKTS-03).
  - The experiment record has a reason field.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-039 — No tuning on the paper stream
- **Source:**
  - `REQUIREMENTS.md` PAPER-03
  - ROADMAP Phase 7 SC3: "registry diff proves no parameter change touched the running stream"
- **Exact rule:** During paper forward observation, the parameter set in use is pinned. No parameter change may affect the running stream.
- **Scope:** paper
- **Affected entities/modules:** `src/paper/freeze.py`, `.github/workflows/paper_freeze_check.yml`
- **Expected state transitions:** n/a
- **Verification targets:** A pinned epoch or hash is checked on every tick, and a mismatch halts or fails closed.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-040 — A strategy change creates a new version and a new backtest
- **Source:**
  - `TRADING_STRATEGY_SPEC.md` §12 (L99–111)
  - `AGENT_INSTRUCTIONS.md` §7
  - `RESEARCH_PROTOCOL.md` §0
- **Exact rule:**
  - Any change to detection, entry, SL, TP, invalidation, expiry or feature definitions creates a new strategy version and a new backtest record.
  - A semantic protocol change triggers a new strategy-version lineage.
- **Scope:** all
- **Affected entities/modules:** `src/core/*`, `params/**`
- **Expected state transitions:** n/a
- **Verification targets:** Git history: were `core/` logic changes accompanied by a strategy_version bump in params?
- **Ambiguity:** AMB-021
- **Domain soundness:** OK

---

## E. Trade planning

### INV-041 — A trade plan is complete
- **Source:**
  - `GLOSSARY.md` §1 TradePlan
  - `ARCHITECTURE.md` §2 Trade Planner
  - STRAT-03
  - `00_PRODUCT_SCOPE.md` §4
  - `DATA_MODEL.md` §2.4
- **Exact rule:**
  - Every valid setup becomes a plan carrying direction, entry zone (min/max), SL, TP(s), invalidation rule, expiry, expected RR and plan_hash.
  - Once sized, the plan also carries risk_rate, risk_budget, quantity before and after rounding, and quantization_decision.
- **Scope:** all
- **Affected entities/modules:** `src/core/planner.py`, `src/domain/trade_plan.py`
- **Expected state transitions:** plan created in READY
- **Verification targets:**
  - There are no optional or None fields for SL, entry or expiry on a valid plan.
  - `plan_hash` covers all of the executable fields.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-042 — Minimum RR gate
- **Source:**
  - `CONFIGURATION.md` §3 `minimum_rr`
  - `GLOSSARY.md` §9 `RR_TOO_LOW`
  - `params/*` (`minimum_rr = 2.0`)
- **Exact rule:** A plan whose expected RR is below the registered `minimum_rr` is rejected with `RR_TOO_LOW` (NO_TRADE).
- **Scope:** all
- **Affected entities/modules:** `src/core/planner.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Boundary tests exist at exactly the minimum, just below and just above (TESTING_STRATEGY §5).
  - RR is computed against the correct entry reference.
- **Ambiguity:** AMB-004 (which entry reference in the zone)
- **Domain soundness:** OK

---

## F. Approval safety

### INV-043 — No order without an explicit human APPROVE (no auto-approve)
- **Source:**
  - `PROJECT.md` L5 "only places orders after explicit human APPROVE — never auto-trading in V1"
  - D004
  - `TELEGRAM.md` §5
  - APRV-02
  - `AGENTS.md` L17
- **Exact rule:**
  - An order is placed only after an explicit APPROVE action by the authorized user.
  - A notification failure, timeout or missing message never implies approval.
- **Scope:** live
- **Affected entities/modules:** `src/approval/*`, `src/execution/manager.py`, `src/adapters/telegram_callbacks.py`
- **Expected state transitions:** only `APPROVE → TradePlan APPROVED → Order PLANNED`
- **Verification targets:**
  - No default or timeout branch sets APPROVED.
  - The executor refuses a plan that has no approval row with action APPROVE.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-044 — What an approval is bound to
- **Source:**
  - `TELEGRAM.md` §3 (L21–32)
  - APRV-02
  - ROADMAP Phase 8 SC2
- **Exact rule:** An approval is bound to all of the following. A mismatch on any of them rejects the approval:
  - SignalId
  - strategy version
  - exact trade plan hash
  - expiry time
  - user identity / authorized chat
  - one-time approval token
- **Scope:** live, paper
- **Affected entities/modules:** `src/approval/binding.py`, `src/approval/tokens.py`, `src/approval/mapping.py`
- **Expected state transitions:** mismatch → reject; no state change
- **Verification targets:**
  - Each binding field is checked at callback time, and again at execution time.
  - The approval token is stored hashed (`approval_token_hash`).
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-045 — Only the authorized chat/user can approve
- **Source:**
  - `TELEGRAM.md` §3 "user identity / authorized chat"
  - APRV-02
- **Exact rule:** Callbacks from any chat or user other than the configured authorized one are rejected and never change state.
- **Scope:** live, paper
- **Affected entities/modules:** `src/adapters/telegram_callbacks.py`, `src/approval/binding.py`
- **Expected state transitions:** none on unauthorized
- **Verification targets:**
  - Both chat id and user id are checked, as the design requires.
  - The rejection is journaled.
  - The check happens before any DB write.
- **Ambiguity:** AMB-025
- **Domain soundness:** OK

### INV-046 — Approval token is one-time; replay never creates a new order intent
- **Source:**
  - `TELEGRAM.md` §3 L32, §6 (L59–71)
  - `RUNBOOK.md` §6
  - `DATA_MODEL.md` §2.5 L157
  - `TESTING_STRATEGY.md` §10
- **Exact rule:**
  - Callback delivery is at-least-once.
  - A callback carrying an already-consumed token looks up the approval and returns the current approval/order state.
  - Such a callback does not create a new approval, order intent or order.
  - First callback: APPROVED plus at most one execution intent.
- **Scope:** live, paper
- **Affected entities/modules:** `src/approval/replay.py`, `src/approval/tokens.py`, `src/adapters/telegram_callbacks.py`
- **Expected state transitions:** first: `APPROVAL_PENDING → APPROVED` (once); replay: no transition
- **Verification targets:**
  - A 5× duplicate-callback test shows exactly one transition (ROADMAP Phase 8 SC2).
  - Token consumption is atomic (unique constraint or `SELECT ... FOR UPDATE`) under concurrent duplicate callbacks.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-047 — Approval expires; stale or invalid plans cannot be approved
- **Source:**
  - `EXECUTION_SPEC.md` §1 L25
  - `01_ENGINEERING_PRINCIPLES.md` §10
  - `SIGNAL_AND_ALERTS.md` §6 "No stale plan may be approved"
  - `AGENTS.md` L17
  - `GLOSSARY.md` §9 `APPROVAL_EXPIRED`, `STALE_SETUP`, `INVALIDATED`
- **Exact rule:** An approval after expiry, or for a plan that is EXPIRED, INVALIDATED, SUPERSEDED or otherwise stale, is rejected with `APPROVAL_EXPIRED`, `STALE_SETUP` or `INVALIDATED`.
- **Scope:** live, paper
- **Affected entities/modules:** `src/approval/binding.py`, `src/execution/gates.py`
- **Expected state transitions:** expired → no APPROVED
- **Verification targets:**
  - The time comparison uses UTC.
  - The expiry boundary is tested at exactly the expiry instant.
  - The check is repeated at execution time, not only at callback time.
- **Ambiguity:** AMB-013
- **Domain soundness:** OK

### INV-048 — Approval is auditable
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` §10
  - `DATA_MODEL.md` §2.5
- **Exact rule:** Every approval interaction is persisted with its action, request hash, token hash, actor, requested/acted timestamps, Telegram message id and result.
- **Scope:** live, paper
- **Affected entities/modules:** `src/domain/approval.py`, `src/db/models.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Rejected and unauthorized attempts are also persisted or journaled.
  - `actor_id` is populated.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-049 — Risk re-check after APPROVE, before placement
- **Source:**
  - `EXECUTION_SPEC.md` §1 (L7–23): `APPROVE → Risk re-check → Place entry`
  - `RISK_MANAGEMENT.md` §12 L143
- **Exact rule:**
  - After approval and before placing the entry, risk and portfolio constraints are re-evaluated against current state.
  - A plan calculated with stale constraints must be revalidated before approval/execution.
- **Scope:** live
- **Affected entities/modules:** `src/execution/manager.py`, `src/execution/gates.py`, `src/risk/portfolio.py`
- **Expected state transitions:** re-check fails → no order (NO_TRADE with reason)
- **Verification targets:** `execute_approved_plan`, or its equivalent, calls the portfolio gates and the constraint-freshness check with current (reconciled) state.
- **Ambiguity:** AMB-014
- **Domain soundness:** OK

### INV-050 — Telegram message contents
- **Source:**
  - `TELEGRAM.md` §4 (L34–49)
  - APRV-01
  - `SIGNAL_AND_ALERTS.md` §5 L109
- **Exact rule:**
  - The message shows symbol, direction, setup, entry, SL, TP(s), R:R, risk %, expiry, invalidation, current exposure and reason codes.
  - All numbers come from deterministic engine output.
- **Scope:** paper, live
- **Affected entities/modules:** `src/adapters/telegram_notify.py`, `src/paper/notify.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Every field is present.
  - The renderer does not recompute values independently.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-051 — `[PLANNED, not yet canonical]` Money amounts in notifications
- **Source:** ROADMAP Phase 16
- **Exact rule:**
  - SIMULATE and APPROVE messages show quantity, notional, required margin, estimated loss at SL and profit at each TP (gross and net), and the sizing equity with its source and timestamp.
  - The values come from `SizedResult` and are not recomputed.
  - A NO_TRADE message states its reason.
- **Scope:** paper, live
- **Affected entities/modules:** `src/adapters/telegram_notify.py`, `src/paper/notify.py`
- **Expected state transitions:** n/a
- **Verification targets:** Absent today, per ROADMAP. Record as a GAP, not a defect.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-052 — Telegram unavailable: journal signals and never infer approval
- **Source:** `TELEGRAM.md` §5 (L51–57)
- **Exact rule:** If Telegram is unavailable:
  - signals are still journaled;
  - no live order is inferred from the missing notification;
  - the system does not auto-approve.
- **Scope:** paper, live
- **Affected entities/modules:** `src/adapters/telegram_notify.py`, `src/paper/journal.py`
- **Expected state transitions:** Signal stays DETECTED/NOTIFY-failed; no plan APPROVED
- **Verification targets:**
  - A send failure does not abort journaling.
  - A delivery-failure health signal is raised (SECURITY §4 "Telegram delivery").
- **Ambiguity:** none
- **Domain soundness:** OK

---

## G. Risk sizing and quantization

### INV-053 — Size comes from equity × risk_rate and SL distance, not from leverage
- **Source:**
  - `RISK_MANAGEMENT.md` §1–§2 (L5–32)
  - RISK-01
  - ROADMAP Phase 5 SC1
- **Exact rule:**
  - `allowed_risk = equity × risk_rate`
  - `risk_per_unit = worst_case_distance_to_SL + modeled_costs`
  - `quantity = allowed_risk / risk_per_unit`
  - Leverage is never the starting point for size.
- **Scope:** all
- **Affected entities/modules:** `src/risk/sizing.py`, `src/backtest/costs.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The formula matches.
  - `risk_per_unit` is in quote units (price distance), and the costs are converted to quote per unit before they are added (see INV-054).
  - Leverage does not affect quantity.
- **Ambiguity:** AMB-002, AMB-003, AMB-004
- **Domain soundness:** QUESTIONABLE (dimensionally underspecified: "distance + modeled_costs" adds a price to costs whose unit is not stated. Fees are rate × price, so adding a raw rate is a unit error; ROADMAP P11 confirms this)

### INV-054 — Costs are included in risk in the same units
- **Source:**
  - `RISK_MANAGEMENT.md` §2–§3
  - ROADMAP Phase 11 (a confirmed bug description, cited as a planning statement, not an authority): "modeled_costs_per_unit returns the rate sum … adds it to an SL distance in quote currency … costs effectively ignored"
- **Exact rule:**
  - Entry fee, exit fee, expected slippage (and funding and partial-fill effects where applicable) are part of `risk_per_unit`.
  - They are expressed in quote currency per unit before being added to the SL distance.
  - Phase 11 plan: entry fee × entry reference price plus exit fee × SL price.
- **Scope:** all
- **Affected entities/modules:** `src/backtest/costs.py` (`modeled_costs_per_unit`), `src/risk/sizing.py` (`size_position`)
- **Expected state transitions:** n/a
- **Verification targets:**
  - Is a unit-dimensionless rate (0.0008) added to a price distance?
  - Is realized SL loss ≤ `allowed_risk` after fees?
  - This is KNOWN (ROADMAP Phase 11).
- **Ambiguity:** AMB-002, AMB-005
- **Domain soundness:** OK

### INV-055 — Quantity is floored to stepSize and never rounded up
- **Source:**
  - `RISK_MANAGEMENT.md` §11 (L106–119)
  - `TESTING_STRATEGY.md` §9 L135: "A rounded-up quantity is a test failure"
  - `AGENTS.md` L16
  - `RESEARCH_PROTOCOL.md` §2
- **Exact rule:**
  - `rounded_quantity = floor(raw_quantity / step_size) × step_size`, in Decimal.
  - Rounding up is forbidden.
  - NO_TRADE is preferred over round-up.
- **Scope:** all
- **Affected entities/modules:** `src/risk/quantization.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Uses `ROUND_FLOOR` / `ROUND_DOWN` with Decimal.
  - Never `round()` or `quantize` with `ROUND_HALF_*`.
  - Negative or zero raw quantities are handled.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-056 — Minimum risk utilization after rounding (60% baseline)
- **Source:**
  - `RISK_MANAGEMENT.md` §11 rule 3 (L117), L121–127
  - `CONFIGURATION.md` §3
  - `params/*` (`minimum_risk_utilization_after_rounding = 0.6`)
- **Exact rule:** If realized risk after rounding is below the configured `minimum_risk_utilization_after_rounding` × intended risk, reject with `QUANTIZATION_REJECT` (or the fine-grained `UTILIZATION_REJECT`). Quantity is never silently increased.
- **Scope:** all
- **Affected entities/modules:** `src/risk/quantization.py`, `src/risk/sizing.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The threshold is read from the parameter set, not hard-coded.
  - Boundary test at exactly 60%.
  - The v1 TOML comments state "RESERVED … no reader in src/"; check that v2/v3 sets are actually read.
- **Ambiguity:** AMB-006, AMB-007, AMB-008
- **Domain soundness:** OK

### INV-057 — Reject below minQty or minNotional
- **Source:**
  - `RISK_MANAGEMENT.md` §11 rule 2 (L116)
  - `AGENTS.md` L16
  - `RESEARCH_PROTOCOL.md` §2 step 3
- **Exact rule:** If the floored quantity is below `minQty`, or its notional is below `minNotional`, reject with `MIN_QTY_REJECT` / `NOTIONAL_REJECT` (or `MIN_NOTIONAL_REJECT`).
- **Scope:** all
- **Affected entities/modules:** `src/risk/quantization.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Notional uses a documented price reference.
  - Zero quantity after floor is rejected.
  - Values come from symbol metadata.
- **Ambiguity:** AMB-006, AMB-008, AMB-027
- **Domain soundness:** QUESTIONABLE (the rule is sound, but at $500–1,000 and 0.5% risk ($2.5–5), Binance minNotional (about 100 USDT on BTCUSDT, lower on alts; re-verify) rejects setups with a wide SL. The NO_TRADE rate from this should be measured)

### INV-058 — Identical quantization and sizing logic in backtest, paper and live
- **Source:**
  - `RISK_MANAGEMENT.md` §11 rule 4
  - `RESEARCH_PROTOCOL.md` §2 "identical … Any divergence must be reported as an incident and fixed in the engine, not patched at the call site"
  - `IMPLEMENTATION_PLAN.md` Phase 1 exit gate
  - RISK-01
  - ROADMAP Phase 5 SC3
- **Exact rule:**
  - One sizing and quantization implementation is shared by all modes.
  - Identical inputs produce identical outputs.
  - There are no call-site patches.
- **Scope:** all
- **Affected entities/modules:** `src/risk/*`, `src/backtest/simulator.py`, `src/paper/loop.py`, `src/execution/manager.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - All three modes call the same function.
  - A parity fixture exists.
  - No mode-specific branch exists inside sizing.
- **Ambiguity:** AMB-005 (Phase 11 live-vs-backtest fee inputs)
- **Domain soundness:** OK

### INV-059 — Sizing is logged
- **Source:**
  - `RISK_MANAGEMENT.md` §11 rule 5
  - `TESTING_STRATEGY.md` §9
  - `DATA_MODEL.md` §2.4
- **Exact rule:**
  - Raw quantity, rounded quantity and realized risk are logged and persisted on the plan.
  - Fixtures carry raw_quantity, rounded_quantity, risk_before_rounding, risk_after_rounding and quantization_decision.
- **Scope:** all
- **Affected entities/modules:** `src/risk/types.py`, `src/domain/trade_plan.py`, `tests/fixtures/**`
- **Expected state transitions:** n/a
- **Verification targets:** Fields exist and are populated.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-060 — Exchange constraint snapshot stored before live placement; stale snapshots rejected
- **Source:**
  - `RISK_MANAGEMENT.md` §12 (L129–143)
  - ROADMAP Phase 9 SC2
  - `IMPLEMENTATION_PLAN.md` Phase 3 "exchange-constraint snapshots"
  - `params` `constraint_snapshot_ttl_seconds = 3600`
  - `GLOSSARY.md` §9 `STALE_CONSTRAINTS`
- **Exact rule:**
  - The constraints used for sizing are persisted: tick, step, minQty, notional, leverage/margin and `observed_at`.
  - A plan sized with stale constraints is revalidated (or rejected with `STALE_CONSTRAINTS`) before approval/execution.
  - Live constraints are revalidated from `exchangeInfo` at placement.
- **Scope:** live
- **Affected entities/modules:** `src/execution/gates.py`, `src/data/metadata.py`, `src/risk/gating.py`
- **Expected state transitions:** stale → STALE_CONSTRAINTS reject or re-size
- **Verification targets:**
  - The TTL comes from the parameter set.
  - Placement-time revalidation re-fetches or uses a fresh snapshot.
  - The snapshot is persisted with the order.
- **Ambiguity:** AMB-014
- **Domain soundness:** OK

### INV-061 — No revenge or compensation risk
- **Source:** `RISK_MANAGEMENT.md` §7 (L67–69)
- **Exact rule:** Risk is never increased because of previous losses or an unmet daily target.
- **Scope:** all
- **Affected entities/modules:** `src/risk/*`
- **Expected state transitions:** n/a
- **Verification targets:** `risk_rate` is not a function of recent PnL or daily state (other than reducing risk to zero at DAILY_STOP).
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-062 — No forced daily trading target
- **Source:**
  - `00_PRODUCT_SCOPE.md` §8
  - D010
  - `METRICS.md` §7
  - `RESEARCH_PROTOCOL.md` R5
- **Exact rule:**
  - The system never forces trades to reach a PnL target.
  - A zero-trade day is valid.
  - Daily PnL is an output metric, not a strategy constraint.
- **Scope:** all
- **Affected entities/modules:** `src/core/*`, `src/risk/*`
- **Expected state transitions:** n/a
- **Verification targets:** No "target" or "quota" logic appears in the strategy or risk code.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## H. Portfolio limits, daily loss, leverage and margin

### INV-063 — Max open positions
- **Source:**
  - `RISK_MANAGEMENT.md` §4 (L44–53) "max open positions: 2" (research placeholder)
  - RISK-02
  - `params` `max_open_positions = 2`
  - `GLOSSARY.md` §9 `MAX_POSITIONS_REJECT`
- **Exact rule:** A new entry is rejected with `MAX_POSITIONS_REJECT` when the open-position count reaches `max_open_positions`.
- **Scope:** all
- **Affected entities/modules:** `src/risk/portfolio.py`, `src/risk/gating.py`, `src/execution/gates.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The count uses reconciled or exchange state in live (ROADMAP Phase 9 "reconciled-state portfolio gates").
  - The limit comes from the parameter set.
  - Boundary: exactly at the limit.
- **Ambiguity:** AMB-017
- **Domain soundness:** OK

### INV-064 — Max aggregate open risk
- **Source:**
  - `RISK_MANAGEMENT.md` §4 "max aggregate open risk: 1.0%"
  - `params` `max_aggregate_open_risk = 0.01`
  - `GLOSSARY.md` §9 `AGGREGATE_CAP_REJECT` / `RISK_LIMIT`
- **Exact rule:** A new entry is rejected when (existing open risk + the new plan's risk) exceeds `max_aggregate_open_risk × equity`.
- **Scope:** all
- **Affected entities/modules:** `src/risk/portfolio.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Existing open risk includes pending (unfilled) approved entries, per the design decision.
  - Boundary at equality.
  - Decimal arithmetic.
- **Ambiguity:** AMB-017
- **Domain soundness:** OK

### INV-065 — Correlated cluster cap
- **Source:**
  - `RISK_MANAGEMENT.md` §4 "max risk for one correlated cluster: TBD", §5 (L55–59)
  - RISK-02
  - `params` `cluster_cap = 0.005`
  - `GLOSSARY.md` §9 `CLUSTER_CAP_REJECT` / `CORRELATED_RISK_LIMIT`
- **Exact rule:**
  - Directionally aligned trades in correlated symbols (for example BTC/ETH/SOL/XRP) are not treated as independent.
  - Risk per cluster is capped by `cluster_cap`.
- **Scope:** all
- **Affected entities/modules:** `src/risk/portfolio.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The cluster membership definition exists and is versioned.
  - Direction-awareness is handled.
  - Cap source is the parameter set.
- **Ambiguity:** AMB-016
- **Domain soundness:** QUESTIONABLE (all live-5 symbols are highly correlated crypto beta. cluster_cap = risk_rate allows one aligned position at most, while max_open_positions = 2, and the docs never define cluster membership)

### INV-066 — Daily loss state machine: NORMAL, WARNING, DAILY_STOP
- **Source:**
  - `GLOSSARY.md` §8.1 (L126–136)
  - `RISK_MANAGEMENT.md` §8 (L71–85)
  - RISK-02
  - ROADMAP Phase 9 SC2 "DAILY_STOP is enforced against live state"
  - `params` warning 0.005 / stop 0.01
- **Exact rule:**
  - NORMAL: below warning, entries allowed.
  - WARNING: warning reached, entries allowed, alert fires.
  - DAILY_STOP: stop reached, no new entries (`DAILY_STOP` / `DAILY_STOP_BLOCK`), existing protective exits stay active, user alerted.
- **Scope:** all
- **Affected entities/modules:** `src/risk/gating.py`, `src/risk/portfolio.py`, `src/execution/gates.py`
- **Expected state transitions:** `NORMAL → WARNING → DAILY_STOP`. The reset at day boundary is unspecified.
- **Verification targets:**
  - DAILY_STOP blocks entries but never cancels protective exits.
  - The alert is sent.
  - The daily loss input source in live is noted as KNOWN in ROADMAP Phase 12 (caller-injected).
- **Ambiguity:** AMB-012
- **Domain soundness:** UNKNOWN (daily loss basis, the realized/unrealized split and the day boundary are undefined; with a 1% stop and 0.5% risk, two losses halt the day)

### INV-067 — `[PLANNED, not yet canonical]` Equity and daily PnL from Binance
- **Source:**
  - ROADMAP Phase 12
  - canonical support: `01_ENGINEERING_PRINCIPLES.md` §3 (Binance authoritative for positions/PnL/commissions)
  - `RISK_MANAGEMENT.md` §10
- **Exact rule:**
  - In live mode, equity and daily realized loss come from Binance, through the account endpoint and user-data stream.
  - Unknown or stale equity leads to NO_TRADE.
  - Equity is not derived by summing own PnL.
- **Scope:** live
- **Affected entities/modules:** `src/risk/types.py` (`AccountState`), `src/adapters/binance_usdm.py`, `src/execution/manager.py`
- **Expected state transitions:** unknown equity → fail closed
- **Verification targets:** Who supplies `AccountState.equity` in live? KNOWN GAP (ROADMAP Phase 12).
- **Ambiguity:** AMB-018
- **Domain soundness:** OK

### INV-068 — Leverage is a constraint, read before live placement
- **Source:**
  - `RISK_MANAGEMENT.md` §2, §9 (L87–91)
  - `BINANCE.md` §7
- **Exact rule:**
  - Leverage and margin are exchange/account constraints, never the reason for a size.
  - Current account and symbol constraints (including leverage) are read and recorded before live placement.
- **Scope:** live
- **Affected entities/modules:** `src/execution/gates.py`, `src/adapters/binance_usdm.py`, `src/data/metadata.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Leverage and margin mode are read and recorded before placement.
  - They appear in the constraint snapshot (INV-060).
- **Ambiguity:** AMB-019
- **Domain soundness:** QUESTIONABLE (leverage does not change risk-based size, but on Binance it sets initial margin and liquidation distance. Treating it as read-only leaves the account default in place (often high), so liquidation can come before the SL; the docs have no liquidation-vs-SL check)

### INV-069 — `[PLANNED, not yet canonical]` Explicit leverage and margin type; liquidation beyond SL
- **Source:** ROADMAP Phase 13
- **Exact rule:**
  - Before an entry, leverage and margin type are set explicitly per symbol from a versioned parameter.
  - The order is refused (NO_TRADE) unless the projected liquidation price lies strictly beyond the SL.
  - Brackets and maintenance margin come from exchange data.
- **Scope:** live
- **Affected entities/modules:** `src/execution/*`, `src/adapters/binance_usdm.py`
- **Expected state transitions:** guard fails → NO_TRADE
- **Verification targets:** KNOWN GAP: nothing sets leverage, per ROADMAP.
- **Ambiguity:** AMB-019
- **Domain soundness:** OK

### INV-070 — Available margin covers the new order before placement
- **Source:**
  - `GLOSSARY.md` §9 `INSUFFICIENT_MARGIN`
  - `RISK_MANAGEMENT.md` §2 "leverage/margin requirements"
  - ROADMAP Phase 14 `[PLANNED]`
- **Exact rule:** An entry is not placed unless `availableBalance` covers its initial margin at the configured leverage plus fees. Otherwise the result is NO_TRADE with `INSUFFICIENT_MARGIN`.
- **Scope:** live
- **Affected entities/modules:** `src/execution/gates.py`
- **Expected state transitions:** reject → NO_TRADE
- **Verification targets:** KNOWN GAP (ROADMAP Phase 14). Is `INSUFFICIENT_MARGIN` ever produced?
- **Ambiguity:** AMB-019
- **Domain soundness:** OK

### INV-071 — `[PLANNED, not yet canonical]` Live price checked against SL and entry zone before placement
- **Source:**
  - ROADMAP Phase 15
  - canonical support: `EXECUTION_SPEC.md` §4 item 4 "symbol/market conditions make the plan stale"
- **Exact rule:** Between APPROVE and placement, the system confirms that the mark or last price has not crossed the SL, and has not left the entry zone in a way that would make the entry fill instantly into a triggered SL. Otherwise it fails closed with a dedicated reason.
- **Scope:** live
- **Affected entities/modules:** `src/execution/manager.py` (`execute_approved_plan`), `src/execution/gates.py`
- **Expected state transitions:** reject → no order
- **Verification targets:** KNOWN GAP (ROADMAP Phase 15, "verify first").
- **Ambiguity:** AMB-014
- **Domain soundness:** OK

### INV-072 — Uncertain account or risk state fails closed
- **Source:**
  - `RISK_MANAGEMENT.md` §10 (L93–100)
  - `01_ENGINEERING_PRINCIPLES.md` §9
  - RISK-02
  - `GLOSSARY.md` §9 `UNCERTAIN_ACCOUNT_STATE`, `RECONCILIATION_REQUIRED`
- **Exact rule:** If account equity, open positions or existing orders cannot be reconciled, no new order is placed. The result is NO_TRADE with `UNCERTAIN_ACCOUNT_STATE` or `RECONCILIATION_REQUIRED`.
- **Scope:** all (live primary)
- **Affected entities/modules:** `src/risk/gating.py`, `src/execution/gates.py`, `src/reconcile/*`
- **Expected state transitions:** uncertain → NO_TRADE
- **Verification targets:**
  - None or unknown account fields yield a rejection, not a default of 0.
  - Exceptions in the account fetch do not fall through to placement.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## I. Fail-closed behavior and SAFE_MODE

### INV-073 — General fail-closed rule
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` §9 (L83–89)
  - `AGENTS.md` L18
  - `PROJECT.md` L55
- **Exact rule:** When data integrity, connection state, account state or risk state is uncertain, the result is NO TRADE and no new order is placed.
- **Scope:** all
- **Affected entities/modules:** `src/execution/*`, `src/paper/*`, `src/risk/gating.py`, `src/reconcile/*`
- **Expected state transitions:** → NO_TRADE / SAFE_MODE
- **Verification targets:**
  - Broad `except:` blocks do not default to "proceed".
  - Unknown enum values from the exchange result in reject.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-074 — SAFE_MODE semantics
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §7 (L76–82)
  - `RUNBOOK.md` §2
  - OPS-01
  - ROADMAP Phase 8 SC5
- **Exact rule:** While SAFE_MODE is active:
  - no new live order placement (entries);
  - existing exchange-side protective orders stay active and are not canceled;
  - monitoring, journaling and reconciliation continue.
- **Scope:** live, paper
- **Affected entities/modules:** `src/reconcile/safe_mode.py`, `src/execution/gates.py`, `src/execution/manager.py`
- **Expected state transitions:** any → SAFE_MODE; exit criteria are unspecified (AMB-015)
- **Verification targets:**
  - The execution gate checks SAFE_MODE.
  - SAFE_MODE entry does not cancel stops.
  - The SAFE_MODE flag is persisted, so it survives a restart.
  - Protective re-placement or the sweeper under SAFE_MODE is handled (AMB-024).
- **Ambiguity:** AMB-015, AMB-024
- **Domain soundness:** QUESTIONABLE (a literal "no new orders" under SAFE_MODE also forbids re-placing a missing protective stop, which would leave a naked position; see AMB-024)

### INV-075 — SAFE_MODE triggers
- **Source:**
  - `RUNBOOK.md` §2 (L11–18), §3, §5, §9
  - EXEC-02 "forces SAFE_MODE on divergence"
- **Exact rule:** SAFE_MODE is entered when:
  - state cannot be reconciled;
  - market data is stale;
  - protective orders are missing or uncertain;
  - duplicate execution is suspected;
  - exchange/API behavior is unexpected;
  - the DB is corrupt or unavailable;
  - reconciliation finds a divergence.
- **Scope:** live
- **Affected entities/modules:** `src/reconcile/compare.py`, `src/reconcile/safe_mode.py`, `src/ops/health.py`
- **Expected state transitions:** → SAFE_MODE
- **Verification targets:** Each trigger has a code path. Drills exist (ROADMAP Phase 8 plan 08-05, still unchecked).
- **Ambiguity:** AMB-015
- **Domain soundness:** OK

### INV-076 — Stale market feed: no new signals and no new orders
- **Source:**
  - `RUNBOOK.md` §7 (L81–97)
  - `DATA_PIPELINE.md` §4, §6 "stale feed"
  - `GLOSSARY.md` §9 `DATA_STALE`
- **Exact rule:**
  - If `now - last_expected_closed_candle > configured freshness threshold`, the system emits no new signals and no new orders, then reconnects or re-bootstraps.
  - It resumes only after candle continuity is validated and the health check passes.
- **Scope:** paper, live
- **Affected entities/modules:** `src/paper/supervisor.py`, `src/paper/resync.py`, `src/ops/health.py`
- **Expected state transitions:** HEALTHY → STALE (block) → HEALTHY after health check
- **Verification targets:**
  - The threshold is configured and not infinite.
  - The block covers both signals and orders.
  - The continuity check runs before resume.
- **Ambiguity:** AMB-023
- **Domain soundness:** OK

### INV-077 — Gaps are journaled; signals are never fabricated
- **Source:**
  - PAPER-01 "journals gaps without fabricating signals"
  - `DATA_PIPELINE.md` §4 "Detect gaps"
- **Exact rule:**
  - A detected gap is journaled.
  - No signal is produced from missing, interpolated or backfilled-late data in a way that would fabricate a past signal.
- **Scope:** paper, live
- **Affected entities/modules:** `src/paper/loop.py`, `src/paper/resync.py`, `src/data/quality.py`
- **Expected state transitions:** n/a
- **Verification targets:** After a REST resync, historical candles in the gap window do not emit stale signals or alerts (see AMB-028).
- **Ambiguity:** AMB-028
- **Domain soundness:** OK

### INV-078 — Live orders disabled by default; explicit enablement
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §2 (L13–21) `LIVE_ORDERS_DISABLED`
  - `AGENT_INSTRUCTIONS.md` §6 "No live order code may be enabled by default … explicit environment guard, dry-run/paper path"
  - ROADMAP Phase 9 plan 09-03 "default-disabled enablement"
- **Exact rule:**
  - After deployment, live execution is disabled.
  - The operator must explicitly enable it.
  - Live order code paths have an environment guard and a dry-run/paper path.
- **Scope:** live
- **Affected entities/modules:** `src/execution/enablement.py`
- **Expected state transitions:** `LIVE_ORDERS_DISABLED → enabled` only by explicit operator action
- **Verification targets:**
  - Default config means disabled.
  - A missing or invalid config means disabled.
  - Enablement is journaled.
  - Enablement is refused at the kill-gate terminal state (INV-098).
- **Ambiguity:** AMB-015, AMB-029
- **Domain soundness:** OK

### INV-079 — Restart sequence
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §8 (L84–96)
  - `BINANCE.md` §10
- **Exact rule:**
  - Restart order: load config → validate time → restore strategy cache → reconcile Binance orders and positions → reconnect streams → verify no duplicate signal or order action → resume only when consistent.
  - Live approval is enabled only after the comparison completes.
- **Scope:** live, paper
- **Affected entities/modules:** `src/paper/supervisor.py`, `src/execution/manager.py`, `src/reconcile/*`
- **Expected state transitions:** startup → (reconciled) → LIVE_APPROVAL
- **Verification targets:** No approval or placement handler is active before the first reconciliation succeeds.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## J. Order placement and execution

### INV-080 — Protective exits use Algo (CONDITIONAL) orders
- **Source:**
  - `EXECUTION_SPEC.md` §2 (L27–37)
  - `BINANCE.md` §6
  - `AGENTS.md` L48–49
  - EXEC-01
  - `IMPLEMENTATION_PLAN.md` Phase 3
- **Exact rule:**
  - STOP_MARKET, TAKE_PROFIT_MARKET and related conditional orders use the Algo Order service (`POST/GET/DELETE /fapi/v1/algoOrder`, `algoType=CONDITIONAL`), never legacy `/fapi/v1/order`.
  - The lifecycle comes from `ALGO_UPDATE`. Rejection reasons are in `ALGO_UPDATE.o.rm`, and `CONDITIONAL_ORDER_TRIGGER_REJECT` is gone.
- **Scope:** live
- **Affected entities/modules:** `src/adapters/binance_usdm.py`, `src/execution/placement.py`, `src/execution/fill_monitor.py`, `src/reconcile/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The SL and TP adapter uses the algo endpoint.
  - The user-data parser handles `ALGO_UPDATE`.
  - No legacy event name is relied on.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-081 — Entry is LIMIT or a defined limit-zone model
- **Source:**
  - `EXECUTION_SPEC.md` §2
  - D011 (provisional)
  - EXEC-01
  - ROADMAP Phase 9 SC1
- **Exact rule:**
  - V1 entry is a `LIMIT` order or a defined limit-zone model.
  - Only order types required by the frozen strategy are implemented.
- **Scope:** live
- **Affected entities/modules:** `src/execution/placement.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Entry order type is LIMIT, with price inside the plan zone and tick-quantized.
  - No MARKET entry path exists.
- **Ambiguity:** AMB-004
- **Domain soundness:** OK

### INV-082 — `closePosition` constraints
- **Source:** `EXECUTION_SPEC.md` §2 L37, §5 (L77–85)
- **Exact rule:**
  - `closePosition=true` is used only on supported market-triggered conditional types.
  - It is never combined with `quantity` or `reduceOnly`.
  - Constraints are mode-dependent, and hedge mode is handled explicitly.
- **Scope:** live
- **Affected entities/modules:** `src/execution/placement.py`, `src/adapters/binance_usdm.py`
- **Expected state transitions:** n/a
- **Verification targets:** Request builders never send `closePosition` together with `quantity` or `reduceOnly`.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-083 — Position mode is detected, never assumed
- **Source:**
  - `EXECUTION_SPEC.md` §8 (L106–112)
  - `BINANCE.md` §7
  - `AGENTS.md` L51
  - EXEC-01 "supports both position modes"
- **Exact rule:**
  - The system detects and records one-way vs hedge mode (and multi-asset mode where relevant).
  - `positionSide` is mandatory in hedge mode.
  - It never assumes one-way.
- **Scope:** live
- **Affected entities/modules:** `src/adapters/binance_usdm.py`, `src/execution/placement.py`
- **Expected state transitions:** unknown mode → fail closed
- **Verification targets:**
  - The mode is fetched from the account.
  - Hedge-mode branches set `positionSide`.
  - One-way mode sends `BOTH` or omits it.
- **Ambiguity:** AMB-030
- **Domain soundness:** OK

### INV-084 — Protective orders sized to the actual filled quantity
- **Source:**
  - `EXECUTION_SPEC.md` §5 (L67–75)
  - EXEC-01
  - ROADMAP Phase 9 SC1
- **Exact rule:**
  - The system supports partial entry fills and cancellation of the remaining entry quantity.
  - Protective exits are sized against the actual filled quantity.
  - The position moves to fully filled when complete.
  - Out-of-order or replayed fill events are reconciled.
- **Scope:** live
- **Affected entities/modules:** `src/execution/fill_monitor.py`, `src/execution/placement.py`
- **Expected state transitions:** `PARTIALLY_FILLED → FILLED`; protective quantity follows fills
- **Verification targets:**
  - Fill folding is idempotent on `(order_id, exchange_trade_id)`.
  - Protective quantity equals cumulative filled quantity, floored to step.
  - TP1 reduceOnly quantity ≤ position.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-085 — Protective stop verified after an entry fill
- **Source:**
  - `EXECUTION_SPEC.md` §6 (L87–98)
  - `IMPLEMENTATION_PLAN.md` Phase 3 exit gate
  - `AGENT_INSTRUCTIONS.md` §6 "protective-order verification"
- **Exact rule:**
  - After an entry fill, the system verifies with Binance that the expected protective stop exists and is active.
  - If protection cannot be confirmed, it raises a HIGH PRIORITY alert and does not assume the position is protected.
- **Scope:** live
- **Affected entities/modules:** `src/execution/fill_monitor.py`, `src/execution/manager.py`, `src/ops/health.py`
- **Expected state transitions:** unconfirmed → alert (+ SAFE_MODE per RUNBOOK §3)
- **Verification targets:**
  - The check queries the exchange (open algo orders), not local state.
  - A timeout means unconfirmed.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-086 — Stop is never silently widened
- **Source:** `RISK_MANAGEMENT.md` §6 (L61–65)
- **Exact rule:**
  - Once a position is protected, the stop is never silently widened.
  - Any stop change is explicit, logged and allowed by the contract.
- **Scope:** live
- **Affected entities/modules:** `src/execution/*`, `src/reconcile/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Any stop re-placement uses the same or a tighter price, is journaled, and never uses a recomputed wider SL.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-087 — Deterministic client IDs: no duplicate entry orders
- **Source:**
  - `EXECUTION_SPEC.md` §7 (L100–104)
  - EXEC-03
  - ROADMAP Phase 8 SC4
  - `IMPLEMENTATION_PLAN.md` Phase 3 exit "no duplicate execution incidents"
- **Exact rule:**
  - Every order request carries a deterministic client identifier (derived from plan and role).
  - Repeated execution of the same approved plan, retries, restarts and replayed events never create a duplicate entry order.
- **Scope:** live
- **Affected entities/modules:** `src/execution/order_ids.py`, `src/execution/manager.py`, `src/db/models.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The ID is a pure function of `(plan_hash/plan_id, role, leg)`.
  - A unique DB constraint exists on `client_order_id`.
  - The ID fits Binance length and charset limits (re-verify: 36 chars, `^[.A-Z:/a-z0-9_-]{1,36}$`).
  - Algo `clientAlgoId` is deterministic too.
- **Ambiguity:** none
- **Domain soundness:** QUESTIONABLE (Binance enforces clientOrderId uniqueness only among open orders (re-verify). A deterministic ID alone does not stop a re-submission after the first order has filled or been canceled, so durable local dedup is required)

### INV-088 — No blind retry on an ambiguous placement
- **Source:**
  - `EXECUTION_SPEC.md` §10 (L134–140)
  - `RUNBOOK.md` §10 "Do not infer absence of an order from a timeout"
  - §3 "Never assume a locally stored order ID means the exchange order exists"
- **Exact rule:** On a timeout or network error during placement:
  - do not retry immediately;
  - query or reconcile by client order ID;
  - retry only if absence is confirmed.
- **Scope:** live
- **Affected entities/modules:** `src/execution/manager.py`, `src/execution/placement.py`, `src/adapters/binance_usdm.py` (tenacity/retry config)
- **Expected state transitions:** `SUBMITTING → UNKNOWN →` (query) `→ NEW` or retry
- **Verification targets:**
  - Retry decorators are not applied to signed order POSTs.
  - The timeout path goes to a query.
  - A duplicate-clientOrderId error from Binance is treated as "exists".
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-089 — Pending-entry expiry and cancellation
- **Source:**
  - `EXECUTION_SPEC.md` §4 (L55–65)
  - `BACKTEST_SPEC.md` §6
  - `GLOSSARY.md` Expiry
  - ROADMAP Phase 9 plan 09-04 "expiry wiring"
- **Exact rule:** An unfilled entry is canceled when any of the following occurs:
  - time expiry;
  - strategy invalidation;
  - the portfolio/risk state no longer permits it;
  - the plan is stale;
  - the user cancels.

  An approved LIMIT order is never left open indefinitely, and an expired plan is never executed.
- **Scope:** live, paper, backtest
- **Affected entities/modules:** `src/execution/manager.py`, `src/execution/fill_monitor.py`, `src/backtest/simulator.py`
- **Expected state transitions:** `NEW → CANCELED | EXPIRED`
- **Verification targets:**
  - An expiry scheduler or sweeper exists in live.
  - Invalidation monitoring runs after placement.
  - GTD or explicit cancel is used.
- **Ambiguity:** AMB-031
- **Domain soundness:** OK

### INV-090 — Algo-order capacity headroom
- **Source:**
  - `EXECUTION_SPEC.md` §12 (L151–155)
  - `AGENTS.md` L15, L51
- **Exact rule:**
  - Do not read `MAX_NUM_ALGO_ORDERS`; the filter was removed.
  - Track the current open algo-order count against the documented 200-per-symbol limit, and leave headroom.
- **Scope:** live
- **Affected entities/modules:** `src/execution/gates.py`
- **Expected state transitions:** insufficient headroom → reject (`EXCHANGE_CONSTRAINT`)
- **Verification targets:**
  - A headroom check runs before placing protective legs.
  - It does not depend on a removed filter.
- **Ambiguity:** AMB-032
- **Domain soundness:** UNKNOWN (the 200-per-symbol limit and the removal of the filter must be re-verified against current Binance docs; no endpoint exposes the value)

### INV-091 — Manual emergency controls
- **Source:**
  - `EXECUTION_SPEC.md` §11 (L142–149)
  - `RUNBOOK.md` §12
  - `TELEGRAM.md` §2 (later actions)
- **Exact rule:**
  - The system provides a safe way to cancel pending strategy orders, disable new live orders, close strategy positions on explicit user action, and switch to SAFE_MODE.
  - A manual close records ManualExit, actor, reason, requested_at_utc and exchange_confirmation.
  - Orphan protectives are canceled afterwards.
- **Scope:** live
- **Affected entities/modules:** `src/execution/enablement.py`, `src/reconcile/safe_mode.py`, `src/ops/drills.py`
- **Expected state transitions:** manual close → Position CLOSED → orphan sweep
- **Verification targets:** Mechanisms exist, and the manual-close record fields exist.
- **Ambiguity:** AMB-033
- **Domain soundness:** OK

---

## K. Reconciliation (the exchange is canonical)

### INV-092 — The exchange is authoritative
- **Source:**
  - `01_ENGINEERING_PRINCIPLES.md` §3 (L33–44)
  - D002
  - `DATA_MODEL.md` §2.9 L263
  - `AGENTS.md` L15
- **Exact rule:**
  - Binance is the source of truth for order status, fills, positions, realized PnL, commissions and conditional orders.
  - User-data WS is preferred for realtime; REST is used for bootstrap and reconciliation.
  - Local state is reconciled from the exchange, never the reverse.
- **Scope:** live
- **Affected entities/modules:** `src/reconcile/*`, `src/execution/fill_monitor.py`, `src/analytics/live_outcomes.py`
- **Expected state transitions:** local state updated from exchange
- **Verification targets:**
  - Commission and realized PnL are taken from fills (`ORDER_TRADE_UPDATE` `n`/`rp`), not recomputed, for live analytics.
  - Conflicts resolve to the exchange.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-093 — Three-source reconciliation; divergence is flagged
- **Source:**
  - `EXECUTION_SPEC.md` §9 (L114–132)
  - `BINANCE.md` §9–§10
  - EXEC-02
  - ROADMAP Phase 8 SC3
- **Exact rule:**
  - On startup, on reconnect and periodically, compare local state against Binance open normal orders, open algo/conditional orders and positions.
  - Any divergence produces `RECONCILIATION_REQUIRED` and forces SAFE_MODE.
  - Reconciliation does not rely only on the WS stream.
- **Scope:** live
- **Affected entities/modules:** `src/reconcile/compare.py`, `src/reconcile/safe_mode.py`
- **Expected state transitions:** divergence → SAFE_MODE
- **Verification targets:**
  - All three sources are queried.
  - A periodic scheduler exists, not only at startup.
  - Unknown exchange orders (TESTING_STRATEGY §11) are flagged.
  - A local order missing on the exchange is flagged.
- **Ambiguity:** AMB-015
- **Domain soundness:** OK

### INV-094 — Orphan protective sweep
- **Source:**
  - `RUNBOOK.md` §4 (L46–62)
  - `EXECUTION_SPEC.md` §9 L130
  - EXEC-02
  - `IMPLEMENTATION_PLAN.md` Phase 3
- **Exact rule:**
  - An active stop or TP whose position is zero, or whose plan is closed or invalid, is an orphan.
  - After authoritative verification that the position is zero, cancel it, journal the cancellation and re-scan.
  - This runs on event-driven reconciliation and on periodic sweeps.
- **Scope:** live
- **Affected entities/modules:** `src/reconcile/sweeper.py`
- **Expected state transitions:** orphan → CANCELED (journaled)
- **Verification targets:**
  - The position=0 check is fresh from the exchange just before the cancel.
  - Both normal and algo orders are swept.
  - The sweep never cancels the protection of a live position (hedge-mode side matching).
- **Ambiguity:** AMB-024
- **Domain soundness:** OK

### INV-095 — Reconnect: re-query authoritative state before resuming
- **Source:**
  - `BINANCE.md` §9–§10
  - `RUNBOOK.md` §8
  - `DATA_PIPELINE.md` §4
  - `SECURITY_AND_OPERATIONS.md` §3
- **Exact rule:**
  - On every reconnect: refresh server time if needed, bootstrap authoritative account and market state, compare, restore subscriptions, verify the latest closed candle, and only then resume.
  - Query both normal and algo orders before resuming live approval.
  - A planned reconnect (24h WS lifetime) is part of normal operation.
- **Scope:** live, paper
- **Affected entities/modules:** `src/paper/supervisor.py`, `src/paper/resync.py`, `src/adapters/paper_ws.py`
- **Expected state transitions:** disconnected → resync → running
- **Verification targets:** A 24h reconnect is handled, and there is no approval or placement during the resync window.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-096 — Fill/event replay is idempotent
- **Source:**
  - `DATA_MODEL.md` §2.8, §5 "Unique constraints must protect … exchange event replay"
  - `EXECUTION_SPEC.md` §5
- **Exact rule:** Replayed or out-of-order user-data events never double-count fills, commission or position quantity.
- **Scope:** live
- **Affected entities/modules:** `src/execution/fill_monitor.py`, `src/db/models.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - A unique `(order_id, exchange_trade_id)` exists.
  - Folding logic uses a set union, not accumulation.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## L. Journal, analytics, and research governance

### INV-097 — System, user and opportunity separation
- **Source:**
  - `METRICS.md` §3
  - `DATA_MODEL.md` §6
  - `RESEARCH_PROTOCOL.md` §6
  - PAPER-02
  - JRN-01
- **Exact rule:**
  - Reports separate: system (all valid signals), user-executed (approved and filled), opportunity (skipped or expired, with a hypothetical outcome under the same assumptions), and NO_TRADE (with a reason category).
  - The four attribution timestamps are recorded: SignalTime, ApproveTime, OrderTime and FillTime.
- **Scope:** paper, live, research
- **Affected entities/modules:** `src/paper/attribution.py`, `src/analytics/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The opportunity outcome uses the same simulator and cost model.
  - The timestamps are persisted.
  - Skipped trades are not dropped.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-098 — Kill gate D013/D030
- **Source:**
  - D013
  - D030
  - `RESEARCH_PROTOCOL.md` §4 "Kill gate D013"
  - `GLOSSARY.md` §8.2
  - `IMPLEMENTATION_PLAN.md` "Project kill gate"
  - GOV-01
- **Exact rule:**
  - The gate fires (INSUFFICIENT_EDGE) only when all three hold:
    - ≥3 independently specified families have been tested under the frozen methodology;
    - ≥6 calendar months have elapsed since 2026-09-19T00:00Z, so the earliest terminal state is 2027-03-19T00:00Z;
    - no family holds a recorded passing decision.
  - Passing is a recorded human decision, never computed.
  - INSUFFICIENT_EDGE is terminal: it keeps live disabled, blocks new family registration, never clears itself, and is recorded as an append-only `KILL_GATE_EVALUATION`.
  - PASSING_CANDIDATE does not authorize live.
- **Scope:** research, live (enablement)
- **Affected entities/modules:** `src/analytics/killgate.py`, `src/analytics/clock.py`, `src/analytics/family.py`, `src/execution/enablement.py`, `docs/research/kill_gate_decisions.json`
- **Expected state transitions:** `WITHIN_BUDGET → PASSING_CANDIDATE | INSUFFICIENT_EDGE` (terminal)
- **Verification targets:**
  - AND logic.
  - Calendar-month arithmetic in UTC.
  - Family independence uses distinct strategy_id, sheet hash and param hashes, with baselines excluded.
  - `enable()` is refused at INSUFFICIENT_EDGE.
  - The registration tripwire exists.
- **Ambiguity:** AMB-034
- **Domain soundness:** OK

### INV-099 — Research protocol freeze uses three witnesses
- **Source:**
  - `RESEARCH_PROTOCOL.md` §0, Appendix A
  - D029
  - `DOC_STATUS.md` L13
  - ROADMAP Phase 1 SC4
- **Exact rule:**
  - The protocol is frozen only when the header, the DECISIONS row and the DOC_STATUS entry agree.
  - A CI gate (`research-gate.yml`) fails on disagreement.
  - A parameter run without a frozen protocol and a registered set is rejected by the gate.
- **Scope:** research
- **Affected entities/modules:** `.github/workflows/research-gate.yml`, `.github/workflows/registry-gate.yml`
- **Expected state transitions:** n/a
- **Verification targets:** The gate checks all three witnesses and is required on PRs.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-100 — Research datasets: three-way split and untouched holdout
- **Source:**
  - `BACKTEST_SPEC.md` §7–§8
  - `RESEARCH_PROTOCOL.md` §1
- **Exact rule:**
  - Data is split Development → Validation → Final holdout/forward.
  - The holdout is never used to choose parameters.
  - Walk-forward periods are fixed before evaluation.
  - Reports show both the research universe and the live-5 universe.
- **Scope:** research, backtest
- **Affected entities/modules:** `src/backtest/experiment.py`, `src/backtest/report.py`, `src/analytics/universe.py`
- **Expected state transitions:** n/a
- **Verification targets:** Split metadata is in the experiment record, and the dual-universe slices are in the report.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-101 — Uncertainty-first reporting
- **Source:**
  - `BACKTEST_SPEC.md` §10, §12 (gates 8–9)
  - `METRICS.md` §8
  - `RESEARCH_PROTOCOL.md` §4
  - BKTS-03
- **Exact rule:**
  - Reports include:
    - trade counts overall and by symbol, quarter and regime;
    - mean, median and SD of R;
    - a (block-)bootstrap interval for expectancy;
    - a resampled drawdown distribution;
    - SE diagnostic alongside the bootstrap SE;
    - a parameter-region analysis.
  - A single headline number never appears alone.
  - Bootstrap is seeded, for determinism.
- **Scope:** research, backtest
- **Affected entities/modules:** `src/backtest/report.py`, `src/analytics/stats.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - A seeded RNG is used.
  - Block bootstrap is available.
  - The full report is not filtered by slice.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-102 — Baseline comparison is mandatory
- **Source:**
  - `BACKTEST_SPEC.md` §9
  - `RESEARCH_PROTOCOL.md` §3 "Baselines"
  - BKTS-02
- **Exact rule:** Every candidate is compared with a no-trade baseline and at least one simple baseline (simple trend filter), using the same engine.
- **Scope:** research, backtest
- **Affected entities/modules:** `src/backtest/experiment.py`, `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`
- **Expected state transitions:** n/a
- **Verification targets:** Baselines are run through the same simulator and appear in the report.
- **Ambiguity:** AMB-020
- **Domain soundness:** OK

---

## M. Backtest semantics

### INV-103 — Intrabar resolution with 1m data and a pre-declared tie-break
- **Source:**
  - `BACKTEST_SPEC.md` §4
  - `RESEARCH_PROTOCOL.md` §3 "Intrabar ambiguity"
  - BKTS-01
  - ROADMAP Phase 6 SC1 "SL-first conservative fallback"
  - `TRADING_STRATEGY_RESEARCH.md` §10.2 "Không được mặc định TP trước" ("must not default to TP first")
- **Exact rule:**
  - If a strategy bar touches both SL and TP, resolve using 1m data.
  - If it is still ambiguous, or 1m is unavailable, apply a conservative deterministic tie-break, fixed before evaluation and declared in the experiment record. TP-first is never the default.
- **Scope:** backtest
- **Affected entities/modules:** `src/backtest/simulator.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The both-touched case uses 1m.
  - The fallback is SL-first.
  - The tie-break is recorded in the experiment record and in the cost/execution hash.
- **Ambiguity:** AMB-035
- **Domain soundness:** OK

### INV-104 — Limit-order simulation checklist
- **Source:**
  - `BACKTEST_SPEC.md` §6
  - `RESEARCH_PROTOCOL.md` §3
  - `TESTING_STRATEGY.md` §7
- **Exact rule:** The simulator models:
  - touched vs filled;
  - a declared partial-fill fraction, applied before TP/SL;
  - time-in-force and expiry;
  - cancel after invalidation;
  - no retroactive fill after expiry;
  - a re-quote after expiry counts as a new order.
- **Scope:** backtest (and the paper simulated path)
- **Affected entities/modules:** `src/backtest/simulator.py`
- **Expected state transitions:** simulated order `NEW → FILLED | PARTIALLY_FILLED | EXPIRED | CANCELED`
- **Verification targets:**
  - A touch at exactly the limit is not automatically a fill under the declared model.
  - Invalidation is checked on closed bars before the fill.
  - Expiry boundary inclusivity.
- **Ambiguity:** AMB-036
- **Domain soundness:** OK

### INV-105 — Costs modeled from experiment #1; slippage is never zero by default
- **Source:**
  - `BACKTEST_SPEC.md` §5
  - `RESEARCH_PROTOCOL.md` §2, R4
  - BKTS-01
  - `METRICS.md` §2 "expectancy … after the defined cost model"
- **Exact rule:**
  - Every run exposes entry fee, exit fee, funding treatment, slippage model and spread/fill assumptions.
  - Slippage is non-zero from the first experiment.
  - Funding applies to positions held through funding events, signed per side.
  - Costs are hashed into `costModelHash` and never retrofitted.
- **Scope:** backtest, paper
- **Affected entities/modules:** `src/backtest/costs.py`, `src/backtest/simulator.py`, `src/backtest/binding.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Zero slippage is rejected or flagged.
  - Funding sign is correct for long vs short.
  - Partial-fill fees are included.
  - Exit slippage is applied too (research §10.5 "tương ứng cho exit", i.e. "the same for exit").
- **Ambiguity:** AMB-005, AMB-037
- **Domain soundness:** QUESTIONABLE (a flat 1 bps slippage is likely optimistic for STOP_MARKET exits and alt symbols. The funding sign convention ("ADDITIVE") is undocumented)

### INV-106 — Invalidation is closed-candle only; setups carry `valid_until`
- **Source:**
  - `RESEARCH_PROTOCOL.md` §6 "Invalidation is closed-candle only; an intrabar touch is not an invalidation"
  - `TRADING_STRATEGY_RESEARCH.md` §13
  - `GLOSSARY.md` Invalidation/Expiry
- **Exact rule:**
  - Every setup has `valid_until` (expiry) and a deterministic invalidation evaluated on closed candles only.
  - Volatility invalidation is used only when the spec calls for it, never "high ATR = news".
- **Scope:** all
- **Affected entities/modules:** `src/core/planner.py`, `src/backtest/simulator.py`, `src/paper/loop.py`, `src/execution/*`
- **Expected state transitions:** plan → INVALIDATED on a closed-candle breach
- **Verification targets:** The invalidation check does not use intrabar high/low of a forming candle.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## N. Data pipeline

### INV-107 — Raw data is immutable; derived data is versioned
- **Source:**
  - `DATA_PIPELINE.md` §8, §13
  - `TECHNOLOGY_STACK.md` §3 "Parquet for immutable raw/derived datasets"
  - `DATA_MODEL.md` §2.1 "immutable normalized OHLCV"
  - D020
- **Exact rule:**
  - Raw market observations are persisted immutably.
  - Derived features carry the calculation timestamp, source candle close time and algorithm version.
  - Published dataset files are never mutated.
  - Parquet/DuckDB holds research data and PostgreSQL holds operational state; PostgreSQL is not the only historical store.
- **Scope:** research, backtest
- **Affected entities/modules:** `src/data/store.py`, `src/data/backfill.py`, `src/data/collector.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - No overwrite or append into existing published Parquet partitions.
  - `dataSnapshotId` identifies an immutable set.
- **Ambiguity:** AMB-038
- **Domain soundness:** OK

### INV-108 — Data quality gates
- **Source:**
  - `DATA_PIPELINE.md` §6 (L68–77)
  - DATA-01
- **Exact rule:** The pipeline rejects or flags:
  - duplicate timestamps;
  - impossible OHLC (high < max(o,c), low > min(o,c), negative values);
  - timestamp regressions;
  - missing sequence;
  - stale feed;
  - symbol metadata mismatch.
- **Scope:** all
- **Affected entities/modules:** `src/data/quality.py`, `src/data/coverage.py`
- **Expected state transitions:** n/a
- **Verification targets:** Each check exists and is used in both the bootstrap and live paths.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-109 — Candle canonical key and per-symbol coverage
- **Source:**
  - `DATA_MODEL.md` §2.1 key `(symbol, timeframe, open_time_utc)`
  - `DATA_PIPELINE.md` §10
- **Exact rule:**
  - Candles are unique on `(symbol, timeframe, open_time_utc)`.
  - Per-symbol `onboard_time`, status history and data start/end are persisted.
  - Reports state the effective date range per symbol.
- **Scope:** research, backtest
- **Affected entities/modules:** `src/data/store.py`, `src/data/coverage.py`, `src/backtest/report.py`
- **Expected state transitions:** n/a
- **Verification targets:** Dedup on the key; the coverage view exists.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-110 — OI collector from day one; funding history
- **Source:**
  - D009
  - D017
  - `DATA_PIPELINE.md` §3, §9, §12
  - DATA-02
- **Exact rule:**
  - Current OI (`/fapi/v1/openInterest`) snapshots are persisted continuously, with timestamp, symbol and OI.
  - Funding history is collected.
  - The sampling interval respects rate limits.
- **Scope:** research
- **Affected entities/modules:** `src/data/collector.py`
- **Expected state transitions:** n/a
- **Verification targets:** The collector persists snapshots idempotently, and duplicates at the same timestamp are deduped.
- **Ambiguity:** none
- **Domain soundness:** OK

---

## O. Security and operations

### INV-111 — Secrets and API key hygiene
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §1, §6
  - `BINANCE.md` §11
  - OPS-02
  - `CONFIGURATION.md` §9
- **Exact rule:**
  - The API key has no withdrawal permission, and an IP allowlist is preferred.
  - Secrets live outside source control, encrypted at rest.
  - Paper/test credentials are separate from live credentials.
  - Keys and signatures are never logged.
  - `pyproject.toml` contains no secrets.
- **Scope:** live, paper
- **Affected entities/modules:** `src/adapters/binance_usdm.py`, `src/adapters/telegram_*`, settings/logging modules
- **Expected state transitions:** n/a
- **Verification targets:**
  - No secrets in the repo.
  - Log calls do not include key, secret, signature, token or URL-with-token.
  - Telegram bot token URLs are not logged.
  - The live/testnet credential split exists.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-112 — Webhook endpoint authenticated; no secrets in the body
- **Source:**
  - `TRADINGVIEW.md` §5, §7
  - `SECURITY_AND_OPERATIONS.md` §1
  - INTG-02 (v2)
  - AGENTS stack "TradingView webhooks (HMAC-checked)"
- **Exact rule:**
  - Any webhook endpoint is authenticated (HMAC per AGENTS), does not accept secrets in the message body, and normalizes the payload to project types before strategy or execution.
  - TradingView is never the execution authority.
- **Scope:** live (optional component)
- **Affected entities/modules:** FastAPI edge (if present); `src/api/` does not exist in the file listing
- **Expected state transitions:** n/a
- **Verification targets:**
  - Whether a webhook exists at all.
  - If one exists, constant-time HMAC comparison and replay protection.
- **Ambiguity:** AMB-039
- **Domain soundness:** QUESTIONABLE (TradingView cannot compute an HMAC over the webhook body. The only options are a static secret in the body or URL, which the doc itself forbids, or IP allowlisting. The "HMAC-checked" requirement is not achievable as written)

### INV-113 — Health checks and high-priority alerts
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §4–§5, §10
  - OPS-02
  - ROADMAP Phase 9 SC3
- **Exact rule:**
  - Monitored: feed freshness, last closed candle, WS and user-data state, REST error rate, reconciliation drift, DB writes, Telegram delivery, unprotected positions, orphans.
  - High-priority alerts fire for: an unprotected position, local ≠ Binance, an unknown order event, a duplicate execution attempt, stale data, a rejected protective action, an auth failure.
  - Health output includes the Python version and git revision.
- **Scope:** live, paper
- **Affected entities/modules:** `src/ops/health.py`
- **Expected state transitions:** n/a
- **Verification targets:** The listed probes exist, and the protective-rejection alert parses `ALGO_UPDATE.o.rm`.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-114 — Structured logging with correlation fields
- **Source:** `SECURITY_AND_OPERATIONS.md` §6 (L61–74)
- **Exact rule:** Logs carry correlation ID, SignalId, OrderId/clientOrderId, symbol, strategy version, UTC timestamp, event type and result, and never secrets.
- **Scope:** all runtime
- **Affected entities/modules:** all runtime modules
- **Expected state transitions:** n/a
- **Verification targets:** A structured logger is used on the execution, approval and reconcile paths.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-115 — Off-host, encrypted backup with a restore drill
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §9
  - `RUNBOOK.md` §11
  - `TECHNOLOGY_STACK.md` §3
  - DATA-04
  - `IMPLEMENTATION_PLAN.md` Phase 0B/3 gates
- **Exact rule:**
  - An automated PostgreSQL backup plus the OI dataset is copied, encrypted, outside the primary host.
  - Retention is documented.
  - A backup is invalid until a restore test succeeds.
  - Backup loss is a data-loss incident.
- **Scope:** ops
- **Affected entities/modules:** `src/ops/backup.py`, `src/ops/drills.py`
- **Expected state transitions:** n/a
- **Verification targets:**
  - The backup target is not the same host.
  - The backup is encrypted.
  - The restore drill is automated.
  - The OI Parquet data is included.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-116 — Normal tests need no network, credentials or DB
- **Source:**
  - `TESTING_STRATEGY.md` §12 (L163–174)
  - AGENTS dev tools "Never hit Binance/Telegram in unit tests"
- **Exact rule:**
  - Strategy and domain tests run without a Binance account, network or database.
  - Integration tests are explicitly marked.
  - A live credential is never required for the normal suite.
- **Scope:** testing
- **Affected entities/modules:** `tests/**`, `pyproject.toml` markers
- **Expected state transitions:** n/a
- **Verification targets:** Markers exist, and there are no network calls in unmarked tests.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-117 — Live dependency discipline
- **Source:**
  - `SECURITY_AND_OPERATIONS.md` §10
  - `TECHNOLOGY_STACK.md` §2, §4
  - `AGENTS.md` stack (legacy connectors archived; no pre-release lines)
- **Exact rule:**
  - Builds use a locked dependency set (`uv.lock`).
  - The official `binance-sdk-derivatives-trading-usds-futures` is used, not archived `binance-connector` or `binance-futures-connector`.
  - Pre-release lines are not used (SQLAlchemy 2.1 RC, Polars 2.0 RC, httpx 1.0).
  - Upgrades are tested on paper/testnet before live.
- **Scope:** live
- **Affected entities/modules:** `pyproject.toml`, `uv.lock`
- **Expected state transitions:** n/a
- **Verification targets:** Pins and lockfile consistency.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-118 — `[PLANNED, not yet canonical]` Quote asset is configuration
- **Source:**
  - ROADMAP Phase 17
  - canonical support: `DATA_MODEL.md` §2.11 (`quote_asset`/`margin_asset` in metadata)
  - `DATA_MODEL.md` §2.11 "Do not hard-code current symbol filters"
- **Exact rule:**
  - The quote and margin asset is configuration, not a constant.
  - An instrument switch requires a DECISIONS entry, new data, a new parameter set and a re-backtest.
- **Scope:** all
- **Affected entities/modules:** `src/data/backfill.py`, `src/backtest/report.py`, `src/analytics/live_outcomes.py`
- **Expected state transitions:** n/a
- **Verification targets:** KNOWN hard-coding (ROADMAP Phase 17).
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-119 — Live universe is limited to the live-5 on the smallest capital
- **Source:**
  - `00_PRODUCT_SCOPE.md` §5
  - `BACKTEST_SPEC.md` §10.1
  - ROADMAP Phase 9 SC3 "first orders only on smallest capital in the live-5 universe"
  - `IMPLEMENTATION_PLAN.md` Phase 3
- **Exact rule:**
  - Live V1 trades only BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT and XRPUSDT.
  - The research universe may be 10–15 symbols.
  - A broader universe must not rescue a weak live-5.
- **Scope:** live, research
- **Affected entities/modules:** `src/execution/gates.py`, `src/analytics/universe.py`
- **Expected state transitions:** n/a
- **Verification targets:** Live placement rejects symbols outside the declared live universe.
- **Ambiguity:** none
- **Domain soundness:** OK

### INV-120 — Phase gates: no live before evidence
- **Source:**
  - D008
  - `IMPLEMENTATION_PLAN.md` Phase 2–3 exit gates
  - `TRADING_STRATEGY_SPEC.md` header and §13
  - `AGENT_INSTRUCTIONS.md` §1, §10
  - ROADMAP Phase 8 dependency note "enablement gates on paper evidence"
- **Exact rule:**
  - Live-approved trading requires the paper exit gate: forward evidence, no unexplained gaps, no paper/backtest divergence, and the runbook exercised.
  - The strategy spec is "implementation-authoritative only after research gates pass". Its acceptance status is currently `Approved for live: NO`.
  - Missing trading rules must stay `TBD` and must not be invented.
- **Scope:** live
- **Affected entities/modules:** `src/execution/enablement.py`, `src/core/*`
- **Expected state transitions:** n/a
- **Verification targets:**
  - Does enablement check any evidence or spec-freeze status?
  - Which rules in `core/` lack a frozen-spec basis?
- **Ambiguity:** AMB-029
- **Domain soundness:** OK

---

## Ambiguities / Contradictions

### AMB-001 — Authority of `AGENTS.md` and `.planning` vs canonical docs
- **Sources:**
  - `RESEARCH_PROTOCOL.md` §2 and §6 cite "`docs/AGENTS.md` Constraints (canonical)".
  - The file is at repo root `AGENTS.md`, and `DOC_STATUS.md` does not list it.
  - `.planning/REQUIREMENTS.md` and `ROADMAP.md` (phases 11–17) add rules absent from canonical docs.
- **Unclear:** Whether AGENTS.md, PROJECT.md and REQUIREMENTS are canonical, and how they rank against DOC_STATUS "baseline" docs such as RISK_MANAGEMENT.
- **Why it matters:** The quantization order (AMB-006) and the headroom source (AMB-032) differ between AGENTS.md and the canonical or baseline docs.
- **Options:**
  - (a) Canonical docs win.
  - (b) AGENTS.md wins, as the protocol claims.
  - (c) The latest-dated statement wins.

### AMB-002 — Units and composition of `risk_per_unit`
- **Sources:**
  - `RISK_MANAGEMENT.md` §2 `risk_per_unit = worst_case_distance_to_SL + modeled_costs` (units unspecified).
  - `TRADING_STRATEGY_RESEARCH.md` §7.1 `quantity = risk_budget / abs(entry - stop)` (no costs; the costs are listed as later "adjustments").
  - `RESEARCH_PROTOCOL.md` §2 `entry_fee` in "basis points per side".
  - params `fee_rate_entry = 0.0002` (fraction).
  - ROADMAP Phase 11 (rate added to a price distance is a bug; convert with entry price and SL price).
- **Unclear:**
  - Whether costs are included in the size denominator at all (research doc says no, risk doc says yes).
  - Which price converts each fee rate (entry vs SL vs TP).
  - Whether funding is included.
  - The unit of fee fields (bps vs fraction).
- **Why it matters:** It decides whether an SL loss can exceed the `risk_rate` budget. Phase 11 confirms this is a live bug.
- **Options:**
  - (a) Costs in quote per unit, as in ROADMAP P11.
  - (b) Costs as a percentage uplift on distance.
  - (c) Exclude costs from sizing and account for them only in PnL.

### AMB-003 — Definition of "equity" for sizing
- **Sources:**
  - `RISK_MANAGEMENT.md` §1–2 "account equity".
  - `00_PRODUCT_SCOPE.md` §10.
  - ROADMAP Phase 12.
- **Unclear:** Wallet balance vs margin balance (including unrealized PnL) vs available balance. Also whether the value is taken at signal time, approval time or placement time.
- **Why it matters:** The size differs, and the plan hash may change between signal and placement.
- **Options:**
  - (a) `totalWalletBalance`.
  - (b) `totalMarginBalance`.
  - (c) A start-of-day equity snapshot.

### AMB-004 — "Worst-case distance to SL" and entry reference for a limit zone
- **Sources:**
  - `RISK_MANAGEMENT.md` §2 "worst_case_distance_to_SL".
  - `DATA_MODEL.md` §2.4 `entry_min_price`/`entry_max_price`.
  - `EXECUTION_SPEC.md` §2 "LIMIT or defined limit-zone model".
  - `TRADING_STRATEGY_SPEC.md` §5 (all TBD).
- **Unclear:**
  - Which zone edge is used for sizing and RR (for a LONG, is the worst case `entry_max`?).
  - Which single price the LIMIT order uses.
  - Whether slippage is added to the worst case.
- **Why it matters:** It determines size, RR gate outcome and realized risk.
- **Options:**
  - (a) The far (adverse) edge.
  - (b) The zone midpoint.
  - (c) The actual limit price chosen by the execution model.

### AMB-005 — Live vs backtest fee inputs vs "identical logic"
- **Sources:**
  - `RISK_MANAGEMENT.md` §11 rule 4.
  - `RESEARCH_PROTOCOL.md` §2 "identical".
  - ROADMAP Phase 11: live uses `GET /fapi/v1/commissionRate`, backtest keeps versioned fees, with fallback to parameter-set fees.
  - `CONFIGURATION.md` §3 (runtime config must never modify strategy semantics).
- **Unclear:**
  - Whether live sizing may use exchange commission (a runtime input) while the plan identity (`parameterSetHash`) records different fees.
  - Whether this violates reproducibility (a plan is no longer reproducible from the parameter set).
- **Why it matters:** Parity tests and plan-hash determinism are at stake.
- **Options:**
  - (a) Treat commission as account state (an input, like equity).
  - (b) Always use parameter-set fees.
  - (c) Use max(param, exchange) as the conservative choice.

### AMB-006 — Order of quantization checks and which rejection code wins
- **Sources:**
  - `AGENTS.md` L16, `PROJECT.md` L53 and `RESEARCH_PROTOCOL.md` §2: floor → realized-risk (60%) → min-qty/notional.
  - `RISK_MANAGEMENT.md` §11: floor → min qty/notional (rule 2) → utilization (rule 3).
- **Unclear:** Which check runs first.
- **Why it matters:** It changes the reported rejection reason (analytics "NO_TRADE by reason category") and golden fixtures, but not whether the trade is taken.
- **Options:**
  - (a) The AGENTS order.
  - (b) The RISK_MANAGEMENT order.
  - (c) Evaluate all and report all.

### AMB-007 — "Realized risk" in the utilization check
- **Sources:**
  - `RISK_MANAGEMENT.md` §11 rule 3.
  - `RESEARCH_PROTOCOL.md` §2 "baseline 60% of intended — exact percentage TBD per risk register and may be tightened in live-mode".
- **Unclear:**
  - The numerator: rounded_qty × distance, with or without costs.
  - The denominator: `allowed_risk` or the raw-qty risk.
  - Whether live may use a different (tighter) threshold than backtest, which conflicts with INV-058.
- **Why it matters:** Boundary behavior at 60%, and mode parity.
- **Options:**
  - (a) rounded/raw quantity ratio.
  - (b) risk_after / allowed_risk.
  - (c) A mode-specific threshold, which would need a decision.

### AMB-008 — Overlapping and duplicate rejection reason codes in GLOSSARY
- **Sources:**
  - `GLOSSARY.md` §9 lists both the older and the Phase-5 codes:
    - `QUANTIZATION_REJECT` and `UTILIZATION_REJECT`
    - `MIN_NOTIONAL_REJECT` and `NOTIONAL_REJECT` (+`MIN_QTY_REJECT`)
    - `DAILY_STOP` and `DAILY_STOP_BLOCK`
    - `RISK_LIMIT` and `AGGREGATE_CAP_REJECT`
    - `CORRELATED_RISK_LIMIT` and `CLUSTER_CAP_REJECT`
  - The same doc says L179: "Do not create synonyms".
  - `RISK_MANAGEMENT.md` §11 names `QUANTIZATION_REJECT` for the utilization failure.
- **Unclear:** Which code must be emitted in each case, and whether the older codes are deprecated.
- **Why it matters:** Analytics category counts, and whether auditors flag code emitting a "wrong" reason.
- **Options:**
  - (a) Fine-grained Phase-5 codes supersede the older ones.
  - (b) The older codes are umbrella categories.
  - (c) Both are emitted.

### AMB-009 — Allowed transition graphs are not specified
- **Sources:**
  - `GLOSSARY.md` §2–§7 (values only).
  - `EXECUTION_SPEC.md` §3 (partial chain: no REJECTED/UNKNOWN edges, no PARTIALLY_FILLED → CANCELED/FILLED edges).
  - `TESTING_STRATEGY.md` §8 (three negative examples only).
- **Unclear:**
  - The full legal transition sets for Signal, TradePlan, Trade and Position.
  - When SignalStatus moves to APPROVED relative to the plan.
  - Whether a signal can go from `NOTIFIED` straight to `APPROVED` without `VIEWED`.
  - The terminal status of a partially filled, then canceled entry.
- **Why it matters:** Auditors cannot classify a transition as illegal without a documented graph.
- **Options:** Derive the graph from code and record it as a decision, or treat it as a spec gap.

### AMB-010 — `TradePlanStatus: CANCELED` example vs the enum
- **Sources:**
  - `TESTING_STRATEGY.md` §8 L113 "TradePlanStatus: CANCELED → APPROVED".
  - `GLOSSARY.md` §3 has no CANCELED in TradePlanStatus.
  - ApprovalAction `CANCEL` exists.
- **Unclear:** Which plan state results from a CANCEL action or a user entry cancel (EXECUTION_SPEC §4 item 5).
- **Why it matters:** Canonical enums and invalid-transition tests.
- **Options:**
  - (a) INVALIDATED.
  - (b) EXPIRED.
  - (c) Add CANCELED, which would need a decision.

### AMB-011 — `SKIP` vs `SKIP_USER`/`SKIP_BUSY`, and how SKIPPED_BUSY arises
- **Sources:**
  - `TELEGRAM.md` §2 "SKIP".
  - `GLOSSARY.md` §4 SKIP_USER and SKIP_BUSY.
  - `SIGNAL_AND_ALERTS.md` §4.
- **Unclear:**
  - Which action the Telegram SKIP button maps to.
  - Whether SKIPPED_BUSY is user-chosen or system-assigned (for example on expiry without a response, where it would overlap EXPIRED).
- **Why it matters:** Opportunity attribution (system vs user vs opportunity) and selection-bias analytics.
- **Options:**
  - (a) Two buttons.
  - (b) SKIP = SKIP_USER, and BUSY is never produced.
  - (c) BUSY is assigned on timeout.

### AMB-012 — Daily loss definition and day boundary
- **Sources:**
  - `RISK_MANAGEMENT.md` §4 "daily loss stop: TBD", §8.
  - `GLOSSARY.md` §8.1 (thresholds "reached").
  - params: warning 0.005, stop 0.01 of equity.
  - ROADMAP Phase 12 "daily realized loss".
  - `01_ENGINEERING_PRINCIPLES.md` §8 (UTC internal).
- **Unclear:**
  - Realized only, or realized plus unrealized; whether fees and funding are included.
  - The equity base: start-of-day or current.
  - The day boundary: 00:00 UTC or 00:00 Asia/Ho_Chi_Minh.
  - The comparison: "reached" means ≥, not >.
  - When DAILY_STOP resets.
  - Canonical docs say TBD, while params fix 1%.
- **Why it matters:** When entries get blocked.
- **Options:** Must be decided explicitly. The configured values are research placeholders.

### AMB-013 — Approval expiry vs plan expiry vs signal expiry
- **Sources:**
  - `TELEGRAM.md` §3 "expiry time".
  - `DATA_MODEL.md` §2.3 `expires_at_utc` and §2.4 `expiry_utc`.
  - params `signal_expiry_hours = 4`.
  - `EXECUTION_SPEC.md` §1.
- **Unclear:**
  - Whether the approval deadline equals the plan expiry, or a shorter approval TTL exists.
  - Whether an approval near expiry may place an entry that is canceled moments later.
- **Why it matters:** The stale-approval window.
- **Options:**
  - (a) Approval deadline = `plan.expiry_utc`.
  - (b) A separate TTL.
  - (c) A minimum remaining validity before placement.

### AMB-014 — Meaning of "risk re-check" and "revalidate" after approval
- **Sources:**
  - `EXECUTION_SPEC.md` §1.
  - `RISK_MANAGEMENT.md` §12 "must be revalidated before approval/execution".
  - `GLOSSARY.md` `STALE_CONSTRAINTS`.
  - ROADMAP Phase 15.
- **Unclear:**
  - Whether revalidation may re-size (change quantity, which changes the plan hash and so the approved plan) or must only accept/reject.
  - Whether live price checks belong in it.
  - What "stale" means in terms of TTL (params say 3600 s, docs give no value).
- **Why it matters:** An approved plan could execute with different parameters than the user approved.
- **Options:**
  - (a) Reject-only with the exact approved quantity.
  - (b) Re-size downward only, with re-approval.
  - (c) Re-size freely, which conflicts with plan-hash binding.

### AMB-015 — SAFE_MODE and RECONCILIATION_REQUIRED status and exit criteria
- **Sources:**
  - `EXECUTION_SPEC.md` §9 "Any divergence enters RECONCILIATION_REQUIRED" (used as a state).
  - `GLOSSARY.md` §9 lists it only as a rejection reason, and §8 SystemMode lacks it.
  - EXEC-02 "forces SAFE_MODE".
  - `RUNBOOK.md` §2 "Only then consider resuming".
  - `SECURITY_AND_OPERATIONS.md` §2 `LIVE_ORDERS_DISABLED` (not a SystemMode).
- **Unclear:**
  - Whether RECONCILIATION_REQUIRED is a mode.
  - Who clears SAFE_MODE (manual only, or automatic after a clean reconciliation).
  - How LIVE_ORDERS_DISABLED relates to the SystemMode values.
  - Whether SAFE_MODE persists across restart.
- **Why it matters:** Automatic resume after a transient divergence could re-enable entries without a human.
- **Options:**
  - (a) Manual clear only.
  - (b) Automatic after N clean reconciliations.

### AMB-016 — Correlated cluster definition
- **Sources:**
  - `RISK_MANAGEMENT.md` §4 "TBD", §5 "conservative cluster rule".
  - params `cluster_cap = 0.005` ("single-trade risk_rate").
- **Unclear:**
  - Which symbols form a cluster (all live-5 as one crypto-beta cluster?).
  - Whether the cap applies per direction.
  - Whether it counts pending entries.
- **Why it matters:** With cap = risk_rate, a second aligned trade is always rejected, so the effective max positions per direction is 1. That may conflict with `max_open_positions = 2`.
- **Options:** Explicit membership plus a direction rule, recorded in the registry.

### AMB-017 — What counts as "open" for position and aggregate-risk limits
- **Sources:**
  - `RISK_MANAGEMENT.md` §4.
  - ROADMAP Phase 9 "reconciled-state portfolio gates".
- **Unclear:**
  - Whether approved-but-unfilled entries (and plans awaiting approval) count toward `max_open_positions` and aggregate open risk.
  - Whether the risk of an open position is its original budget or its current distance to SL.
- **Why it matters:** A race: two approvals could each pass the gate and together exceed the caps.
- **Options:**
  - (a) Count positions only.
  - (b) Count positions plus working entries.
  - (c) Count positions, working entries and pending approvals.

### AMB-018 — Equity and daily-PnL provenance in paper and backtest
- **Sources:**
  - ROADMAP Phase 12 (live from Binance).
  - `01_ENGINEERING_PRINCIPLES.md` §1 (account state is an input).
- **Unclear:**
  - The equity source in paper (a fixed notional, or simulated compounding) and in backtest (fixed or compounding).
  - Whether paper must mirror the live source.
- **Why it matters:** Size parity and the meaning of daily-loss thresholds across modes.
- **Options:** Must be documented per mode.

### AMB-019 — Leverage and margin: read-only constraint or explicitly set parameter
- **Sources:**
  - `RISK_MANAGEMENT.md` §9 "read current account/symbol constraints".
  - `BINANCE.md` §7 "read and record leverage".
  - ROADMAP Phase 13 "set explicitly … from a versioned parameter", with a liquidation guard.
  - Phase 14 (margin check).
  - `CONFIGURATION.md` §3 (strategy parameters vs runtime config).
- **Unclear:**
  - Whether the system may change account leverage or margin type (a write action).
  - Whether leverage belongs in the parameter set (it becomes part of the hash) or in runtime config.
  - Behavior when the account leverage differs from the parameter.
- **Why it matters:** Liquidation before the SL on small accounts.
- **Options:**
  - (a) Read and reject on mismatch.
  - (b) Set explicitly.
  - (c) Runtime config.

### AMB-020 — SignalId collision across parameter sets, baselines and families
- **Sources:**
  - `SIGNAL_AND_ALERTS.md` §3 and `01_ENGINEERING_PRINCIPLES.md` §7: the hash excludes `strategy_id`, `parameterSetHash` and direction.
  - params: `trend-pullback`, `breakout-retest` and `range-mr` all use `strategy_version = "v2.0.0"`.
  - Candidate `trend-pullback/baseline-v3` and the no-trade and simple-trend baselines share strategy_id and version with different parameters.
- **Unclear:**
  - Whether two families (or a candidate and its baseline) evaluated on the same candle with the same setupType produce the same SignalId.
  - Whether a "v2.0.0" version string is global or per strategy_id.
- **Why it matters:** A unique-key conflict could suppress a legitimate signal, or merge attribution across parameter sets.
- **Options:** Include `strategy_id` and/or `parameterSetHash` (and direction) in the hash, or guarantee setupType is globally unique.

### AMB-021 — When a strategy_version bump is required
- **Sources:**
  - `CONFIGURATION.md` §5 "bump the strategy version when behavior changes materially".
  - `TRADING_STRATEGY_SPEC.md` §12 "Any change to detection/entry/SL/TP/invalidation/expiry/feature definition must create a new strategy version".
  - params: v2 and v3 share `v2.0.0`, with v3 "binding-only" cost keys; the no-trade baseline changes `minimum_rr` to 100 under the same version.
- **Unclear:**
  - Whether cost-model or RR-threshold changes count as "material behavior change".
  - Whether version-per-parameter-set is required.
- **Why it matters:** Identity tuples may not distinguish behaviorally different runs by version (the hash still does).
- **Options:**
  - (a) The hash alone suffices.
  - (b) The version must bump for any semantic parameter change.

### AMB-022 — Parameter file format and whole-number normalization
- **Sources:**
  - `CONFIGURATION.md` §6 and §9 "source-controlled JSON/YAML".
  - `RESEARCH_PROTOCOL.md` §5 "numeric type coercion (string-vs-int for whole numbers …)".
  - Actual files are TOML (`params/**/*.toml`), and header comments mention a "whole-number trap" (`partial_fill_fraction = 0.5` chosen "to dodge" it; the no-trade baseline uses `1.0`).
- **Unclear:**
  - Whether TOML is a sanctioned format.
  - How `1.0` vs `1` vs `"1"` normalize.
  - Whether `baseline-no-trade-v1`'s `partial_fill_fraction = 1.0` hashes consistently with its fixtures.
- **Why it matters:** Hash stability and reproducibility.
- **Options:** Document the TOML normalization rule as a decision.

### AMB-023 — Unvalued runtime thresholds
- **Sources:**
  - `RUNBOOK.md` §7 "configured freshness threshold".
  - `DATA_PIPELINE.md` §9 "Every N minutes".
  - `EXECUTION_SPEC.md` §12 "operational headroom".
  - `EXECUTION_SPEC.md` §9 "periodically".
- **Unclear:**
  - The values.
  - Whether they are strategy parameters (hashed) or runtime config (CONFIGURATION §3).
- **Why it matters:** An unset or infinite freshness threshold effectively disables stale-feed fail-closed.
- **Options:** Record the values and their classification.

### AMB-024 — Automatic protective re-placement vs a cancel-only sweeper, and who may call order endpoints
- **Sources:**
  - `RUNBOOK.md` §3 "if stop is absent, submit protection only after risk validation; otherwise require explicit manual intervention".
  - ROADMAP Phase 8 plan 08-04 "cancel-only sweeper".
  - `ARCHITECTURE.md` §2 (only the Execution Manager calls trading endpoints).
  - `SECURITY_AND_OPERATIONS.md` §7 (no new live order placement under SAFE_MODE).
- **Unclear:**
  - Whether, under SAFE_MODE, the system may automatically place a missing protective stop (a new order).
  - Whether the sweeper (reconcile component) may call cancel endpoints directly.
- **Why it matters:** An unprotected position might stay unprotected indefinitely, or conversely, SAFE_MODE might be violated.
- **Options:**
  - (a) Protective-only placements are exempt from SAFE_MODE.
  - (b) Manual only.
  - (c) Automatic with risk validation.

### AMB-025 — Authorized identity: chat id, user id, or both
- **Sources:**
  - `TELEGRAM.md` §3 "user identity / authorized chat".
  - APRV-02 "authorized chat".
- **Unclear:**
  - Whether a group chat with several members is permitted.
  - Whether `from.id` must match as well as `chat.id`.
- **Why it matters:** Another member of an authorized group chat could approve.
- **Options:**
  - (a) Chat only.
  - (b) User only.
  - (c) Both.

### AMB-026 — Trade entity vs order FK
- **Sources:**
  - `DATA_MODEL.md` §4 "Trade 1 — N Order".
  - §2.7 orders FK is `trade_plan_id` (and `position_id`), with no `trade_id`.
  - §1 lists seven entities excluding Trade, while §2.6 defines `trades`.
  - DOMN-01 counts seven entities.
- **Unclear:** Whether Trade is required in V1, and how orders link to trades.
- **Why it matters:** User-performance joins (§6) and the realized_R source.
- **Options:**
  - (a) Link through trade_plan.
  - (b) Add `trade_id` to orders.

### AMB-027 — Price reference for notional checks
- **Sources:**
  - `RISK_MANAGEMENT.md` §11 rule 2.
  - `RESEARCH_PROTOCOL.md` §2 step 3.
- **Unclear:**
  - Whether minNotional uses the entry limit price, mark price or last price.
  - Whether a partial fill below minNotional needs special protective handling.
- **Why it matters:** An exchange rejection at placement vs planned acceptance.
- **Options:**
  - (a) The limit price.
  - (b) The mark price.
  - (c) The more conservative of the two.

### AMB-028 — Signals from candles recovered after a gap
- **Sources:**
  - PAPER-01 "journals gaps without fabricating signals".
  - `RUNBOOK.md` §7–§8 (re-bootstrap, then resume).
  - `SIGNAL_AND_ALERTS.md` §6 "No stale plan may be approved".
- **Unclear:** Whether closed candles recovered by REST resync after a gap may emit signals (they are legitimate closed-candle signals but late), or must be suppressed and journaled as missed.
- **Why it matters:** Late alerts, and prefix-invariance vs live parity.
- **Options:**
  - (a) Suppress and journal.
  - (b) Emit with an immediately-expired status.
  - (c) Emit if still within expiry.

### AMB-029 — Live enablement while the strategy spec is not frozen
- **Sources:**
  - `DOC_STATUS.md` "Blocked until strategy freeze".
  - `TRADING_STRATEGY_SPEC.md` (TEMPLATE, "Approved for live … NO").
  - `AGENT_INSTRUCTIONS.md` §1, §10 (do not invent rules).
  - ROADMAP Phases 4–9 implement three families and a live execution path; Phase 9 SC3 "first orders only on smallest capital".
  - `IMPLEMENTATION_PLAN.md` Phase 2 exit gate.
- **Unclear:**
  - Whether implemented detectors constitute "invented rules".
  - Whether any code-level gate ties live enablement to spec freeze or paper evidence (docs imply one; none is specified).
- **Why it matters:** Live orders could be placed on unvalidated rules.
- **Options:**
  - (a) Enablement must check a spec or evidence flag.
  - (b) An operator procedure only.

### AMB-030 — Position-mode support: "chosen mode" vs "both modes"
- **Sources:**
  - `EXECUTION_SPEC.md` §8 "detect and support the chosen Binance position mode".
  - EXEC-01 and ROADMAP Phase 9 SC1 "supports both position modes".
- **Unclear:** Whether hedge mode must be fully supported, or detected and rejected.
- **Why it matters:** The scope of hedge-mode testing.
- **Options:**
  - (a) Both are supported.
  - (b) One-way is supported and hedge fails closed.

### AMB-031 — Expiry mechanism and boundary
- **Sources:**
  - `EXECUTION_SPEC.md` §4.
  - `BINANCE.md` §6 (GTD must be verified).
  - `TESTING_STRATEGY.md` §5 "expiry timestamp" boundary.
- **Unclear:**
  - Whether exchange-side GTD or a local cancel scheduler is used.
  - Whether expiry is inclusive at `expiry_utc`.
  - Whether a fill racing a cancel is handled.
- **Why it matters:** Orders left open past expiry, and parity with backtest "no retroactive fill after expiry".
- **Options:** Document the mechanism and inclusivity.

### AMB-032 — Source of the 200-conditional-order limit
- **Sources:**
  - `AGENTS.md` L51 "200-conditional-order headroom … must be dynamic via exchangeInfo/account queries, never hard-coded".
  - `EXECUTION_SPEC.md` §12 "Do not read or depend on MAX_NUM_ALGO_ORDERS … removed … documented a 200-open-conditional-order limit per symbol".
- **Unclear:** Whether 200 is a documented constant (hard-coded with a citation) or must be discovered dynamically; no endpoint now exposes it.
- **Why it matters:** An auditor could flag either implementation as a violation.
- **Options:**
  - (a) A config constant with a doc reference.
  - (b) Dynamic discovery (impossible if the filter was removed).

### AMB-033 — Manual-close and CLOSE POSITION scope in V1
- **Sources:**
  - `EXECUTION_SPEC.md` §11 "Must provide a safe way to … close strategy-generated positions".
  - `TELEGRAM.md` §2 lists `CLOSE POSITION` and `SAFE MODE` as "Later".
  - `RUNBOOK.md` §12 record fields.
- **Unclear:** Whether V1 must implement system-mediated close (and cancel entry), or allow manual exchange-side action plus reconciliation.
- **Why it matters:** Gap classification.
- **Options:** V1 required vs later.

### AMB-034 — INSUFFICIENT_EDGE "never clears itself" vs a human reset
- **Sources:**
  - D030 and `GLOSSARY.md` §8.2 "terminal … never clears itself".
  - ROADMAP Phase 10 plan 10-07 "Sticky terminal + human reset".
  - `kill_gate_decisions.json` has `resets: []`.
- **Unclear:** Whether a human reset is sanctioned by a canonical doc (D013 says "until a new evidence-backed research question is approved"), and what evidence or decision record a reset requires.
- **Why it matters:** Governance bypass.
- **Options:** A reset requires a DECISIONS row, or no reset at all.

### AMB-035 — Intrabar tie-break policy: fixed SL-first vs declared per experiment
- **Sources:**
  - `RESEARCH_PROTOCOL.md` §3 lists three permissible policies, "any one, declared in the experiment record".
  - ROADMAP Phase 6 SC1 "SL-first conservative fallback".
  - `BACKTEST_SPEC.md` §4 "conservative deterministic assumption".
- **Unclear:**
  - Whether the policy must be configurable and hashed, or fixed.
  - Whether the "ambiguous bucket" option must be supported.
- **Why it matters:** Experiment identity and reproducibility.
- **Options:**
  - (a) Fixed SL-first, recorded.
  - (b) A declared, hashed field.

### AMB-036 — Partial-fill model vs spread/fill assumption values
- **Sources:**
  - `RESEARCH_PROTOCOL.md` §2 "partial-fill fraction must be declared per experiment".
  - params `spread_fill_assumptions = "FULL_FILL"` with `partial_fill_fraction = 0.5` (v3 sets) and `1.0` (no-trade baseline).
- **Unclear:**
  - What FULL_FILL means when the fraction is 0.5.
  - Whether a touch equals a fill.
  - How the unfilled remainder and its protective sizing are simulated.
- **Why it matters:** Simulated PnL and live parity (EXECUTION_SPEC §5).
- **Options:** Must be defined in a decision.

### AMB-037 — Funding and slippage sign conventions and exit slippage
- **Sources:**
  - `RESEARCH_PROTOCOL.md` §2 "signed per side per the documented convention" (no convention is documented).
  - `effective_entry = intended_entry + slippage` (sign for shorts unspecified).
  - `TRADING_STRATEGY_RESEARCH.md` §10.5 "and correspondingly for exit".
  - params `funding_treatment = "ADDITIVE"`, `slippage_model = "FIXED_BPS"`.
- **Unclear:**
  - The sign for shorts and for exits.
  - Whether funding is received or paid by side.
  - What "ADDITIVE" means.
- **Why it matters:** A wrong sign biases expectancy.
- **Options:** Adverse slippage on every fill, and funding signed by position side times rate (Binance convention).

### AMB-038 — Candle storage location: PostgreSQL `market_candles` vs Parquet
- **Sources:**
  - `DATA_MODEL.md` §2.1 defines `market_candles` as the persistence contract with 1m monthly partitioning.
  - `DATA_PIPELINE.md` §11 (PostgreSQL partitioning) vs §13 "Do not make PostgreSQL the only storage layer for the historical market dataset".
  - D020 (Parquet for research).
- **Unclear:** Which store is canonical for candles used by backtest (`dataSnapshotId`) and by paper.
- **Why it matters:** The definition of immutability and snapshot identity.
- **Options:**
  - (a) Parquet canonical, PG optional.
  - (b) Both, with a sync rule.

### AMB-039 — Webhook adapter scope in V1
- **Sources:**
  - `TRADINGVIEW.md` §7 "If TradingView webhooks are enabled".
  - `REQUIREMENTS.md` INTG-02 (v2).
  - AGENTS stack "FastAPI … TradingView webhooks (HMAC-checked)".
  - `SECURITY_AND_OPERATIONS.md` §1.
- **Unclear:**
  - Whether a webhook exists or is required in V1. The authentication scheme is specified only in AGENTS (HMAC), not in canonical docs.
  - Whether the Telegram callback transport is webhook or polling (FastAPI "Telegram callback receiver (optional)").
- **Why it matters:** The attack surface that security lanes should inventory.
- **Options:** Absent in V1, or present and HMAC-authenticated.

---

## Candidate Doc-Design Concerns

These are the top QUESTIONABLE domain-soundness items, where the documented intent may itself be wrong or incomplete. They are listed for a later lane to check against current Binance documentation and trading practice. None is a confirmed defect.

1. **Cost units in sizing (INV-053, AMB-002):**
   - `risk_per_unit = distance + modeled_costs` is dimensionally underspecified, and the research doc omits costs entirely.
   - Fee rates must be multiplied by a price.
   - This is already confirmed as a live bug in ROADMAP P11, and it means the SL loss can exceed the risk budget.
2. **Leverage treated as read-only (INV-068, AMB-019):**
   - No canonical doc requires a liquidation-vs-SL check or explicit leverage/margin-type setting.
   - Inheriting the account default leverage can put liquidation inside the SL.
   - Only ROADMAP P13, which is not canonical, addresses it.
3. **clientOrderId idempotency (INV-087):**
   - The docs rely on deterministic client IDs.
   - Binance uniqueness applies only among *open* orders (re-verify), so after a fill or cancel the same ID could be accepted again.
   - Durable local dedup is the real guard.
4. **SignalId composition (INV-013, AMB-020):**
   - The hash excludes strategy_id, parameterSetHash and direction.
   - All families and baselines share `strategy_version = "v2.0.0"`.
   - Result: collisions and suppressed signals are possible.
5. **SAFE_MODE "no new orders" vs protective re-placement (INV-074, AMB-024):** A strict reading leaves a position without its stop unprotected.
6. **TradingView "HMAC-checked" webhook (INV-112):**
   - TradingView cannot sign payloads.
   - The only authentication options are a secret in the body or URL (forbidden by TRADINGVIEW §5) or IP allowlisting.
7. **Correlated cluster cap with the live-5 universe (INV-065, AMB-016):**
   - `cluster_cap = risk_rate` combined with an undefined cluster membership effectively caps aligned exposure at one position.
   - This quietly conflicts with `max_open_positions = 2`.
8. **Small-capital feasibility (INV-057):**
   - At $500–1,000 and 0.5% risk, Binance minNotional (about 100 USDT on BTCUSDT; re-verify) rejects setups with wide stops.
   - The NO_TRADE rate this causes is undocumented.
9. **Enum coverage of exchange statuses (INV-024):**
   - A single OrderStatus for normal and algo orders has no documented mapping for EXPIRED_IN_MATCH or the algo lifecycle (TRIGGERED/FINISHED).
10. **Backtest cost realism (INV-105, AMB-037):**
    - A flat 1 bps slippage on STOP_MARKET exits and alts is likely optimistic.
    - The funding sign convention is undocumented.

## Summary

- **Invariants:** 120 (INV-001 … INV-120), of which 6 are tagged `[PLANNED, not yet canonical]`: INV-051, INV-067, INV-069, INV-071, INV-118, plus INV-070 which is partially planned.
- **Domain soundness:** OK = 108, QUESTIONABLE = 10, UNKNOWN = 2 (INV-066, INV-090).
- **Ambiguities:** 39 (AMB-001 … AMB-039).

## Coordinator Review (2026-09-29)
- Structure: 120 unique INV IDs, 39 AMB IDs, no duplicates. Spot-checked the citations for INV-030 (DATA_MODEL §2.2) and INV-066 (RISK_MANAGEMENT §8); both match the source text.
- Caveat: "Affected modules" are file-list pointers, not verified call sites, so lanes must locate the real entry points via codegraph.
- Caveat: "Domain soundness" flags are unverified model knowledge. Stage A (A1/A2) owns the verdicts.
- AMB items are NOT resolved by the audit; they go to report §20 (human decisions).
- APPROVED for use by lanes.
