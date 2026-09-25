---
gsd_state_version: "1.0"
milestone: v0.3
current_phase: 05
status: in_progress
stopped_at: Phase 5 plan 2 complete
last_updated: "2026-09-25T16:00:00.000Z"
last_activity: 2026-09-25
last_activity_desc: Phase 05 plan 2 (portfolio gates + DAILY_STOP + fail-closed) complete
state_head: 4f6d968
progress:
  total_phases: 10
  completed_phases: 0
  total_plans: 20
  completed_plans: 20
current_phase_name: risk-engine
---

<!-- STATE-MD-SCHEMA:END:frontmatter -->

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-19)

**Core value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.
**Current focus:** Phase 04 — pure-core-feature-strategy-planner

## Current Position

Phase: 05 — risk-engine (plan 2 of 2 complete)
Plan: 2 of 2
Status: Phase 05 complete; Phase 6 (backtest) next
Last activity: 2026-09-25 — Phase 05 plan 2 marked complete

Progress: [█████████░] 90%

## Performance Metrics

**Velocity:**

- Total plans completed: 6 (Phase 03 + Phase 05 plans 1+2)
- Average duration: ~14 min
- Total execution time: ~100 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 03 | 4 | 5 | ~12 min |
| 05 | 2 | 2 | ~25 min |

**Recent Trend:**

- Last 6 plans: 03-01 (tracer slice) — ~15 min, 03-02 (six entities) — ~10 min, 03-03 (registry hardening) — ~10 min, 03-04 (ORM mirror + mappers + migration) — ~15 min, 05-01 (risk tracer slice) — ~25 min, 05-02 (portfolio gates) — ~25 min
- Trend: stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 10 fine-grained phases follow evidence order (protocol → data → domain → core → risk → backtest → paper → approval/reconciliation → live → journal/kill-gate); EXEC-02/EXEC-03/OPS-01 harden in Phase 8 before any live order
- [Roadmap]: Strategy V1 family stays TBD (D012); no phase may declare a winner without backtest + out-of-sample evidence
- [Roadmap]: Paper forward-observation (3–6 mo wall-clock) is the schedule long pole; Phase 8 construction may overlap the soak
- [03-01]: D-10 enum values copy GLOSSARY §§2-9 verbatim; str+Enum mixin (not StrEnum) per research canonical pattern
- [03-01]: D-04 parameterSetHash = SHA256 over canonical JSON of normalized TOML body (sorted keys, compact separators, ensure_ascii, allow_nan=False)
- [03-01]: D-03 SignalId input list = strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup_fingerprint
- [03-01]: D-06 closed whitelist of strategy-semantic keys (STRATEGY_KEYS); unknown keys raise StrategyKeyOutsideRegistry
- [03-01]: D-12 float rejected loudly in canonical hash; TOML floats coerced to Decimal via str() before hashing
- [03-02]: D-10 ApprovalResult enum with PENDING, APPROVED, SKIPPED, EXPIRED (planner assumption flagged for user confirmation)
- [03-02]: D-11 Approval carries both result and explicit status (both ApprovalResult); status alone answers state
- [03-02]: D-12 __post_init__ validates Decimal typing on all money/qty/price fields and UTC awareness on all timestamps
- [03-02]: T-03-04 JournalEvent event_type and entity_type are validated non-empty strings; empty values rejected at construction
- [03-02]: DATA_MODEL §2.8 Fill has no status attribute (fills are events, not state)
- [03-02]: DATA_MODEL §2.7 Order carries three independent identifier fields (client_order_id, exchange_order_id, algo_client_id)
- [03-02]: Phase 4 deferral — setup_type, regime, order_role, side, position_side, order_type, time_in_force, event_type, entity_type stay as validated non-empty strings; Enum promotion deferred to Phase 4
- [03-03]: D-04/D-12 trailing precision preserved by reading raw TOML text and building Decimal from string form (1.50 stays Decimal('1.50'), not Decimal('1.5'))
- [03-03]: D-06 parameter names restricted to 7-bit ASCII so code-point sorting matches the documented canonical profile
- [03-03]: D-04 volatile sidecar fields (author, timestamp) never enter the hashed body; editing them does not change the hash
- [03-03]: D-06 check_strategy_key_outside_registry raises StrategyKeyOutsideRegistry if any whitelisted strategy key appears in ambient configuration
- [03-04]: D-02 seven ORM tables on the existing single Base; no separate Base per entity
- [03-04]: D-03 all PKs are content-hash IDs (String(128)); no auto-increment anywhere
- [03-04]: D-11 nullable columns ONLY for 'transition never happened' timestamps
- [03-04]: D-10 Enum translation via .value for storage and Enum(value) for restore; unknown values raise ValueError
- [03-04]: FillRow has unique constraint on (order_id, exchange_trade_id) to protect against duplicate fill ingestion
- [03-04]: CapturingSession pattern snapshots ORM instances BEFORE SQLite roundtrip so NUMERIC lossiness cannot hide mapper errors
- [04-03]: TP2 rule (04-03 checkpoint:decision option A): TP2 = entry_ref + 2 * minimum_rr * risk, where entry_ref = zone mid for LIMIT_ZONE plans
- [04-03]: Setup fingerprint key list: family id, variant codes, regime verdict + confirming 4H bar closes, trigger 1H bar close, zone bounds, ATR value at decision time
- [04-03]: source_timeframe spelling: setup timeframe using exact spelling from tests/fixtures/phase3/candles.csv (lowercase "1h", "4h", "1m"); 4H context folded into fingerprint
- [04-03]: SetupType tokens: TREND_PULLBACK_LONG/SHORT, BREAKOUT_RETEST_LONG/SHORT, RANGE_MR_LONG/SHORT
- [04-03]: Invalidation JSON schema: basis=CANDLE_CLOSE, level=stop_loss_price, break_distance_atr=sl_buffer_atr*ATR
- [04-03]: RR gate is a hard gate returning PlanResult(is_no_trade=True, reason_code=RR_TOO_LOW) — never a downgraded TP1-only plan
- [04-03]: PlanResult envelope: is_no_trade=True requires trade_plan=None; is_no_trade=False requires a TradePlan
- [04-03]: Registry whitelist extended with 7 family B/C keys (D-05); 4 keys assigned to INT_KEYS, rest to DECIMAL_KEYS
- [05-01]: D-05 RejectionReason enum promotion + GLOSSARY §9 update (one-way, locked in plan 05-01 checkpoint:decision)
- [05-01]: D-02 utilization gate = realized_risk / allowed_risk >= 0.6 (Pitfall 2 distinguishing case pinned by parity fixture)
- [05-01]: D-03 notional-check reference price = zone-mid entry_ref (consistent with SL-distance basis)
- [05-01]: D-04 candidate-plan risk ADDED to cap sums in aggregate/cluster caps (Pitfall 6 — exact-cap equality PASSES)
- [05-01]: D-05 new versioned parameter sets named baseline-v2.toml per family at strategy_version v2.0.0 (never ambient v1 edits)
- [05-01]: D-06 src/risk/ is dependency-free (stdlib + Decimal + src/core/_decimal.py only); no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic
- [05-01]: D-07 ConstraintSnapshot type guard rejects zero/negative step_size at construction (fail-closed at type level, not runtime)
- [05-02]: D-01 Gate order fixed (cluster → aggregate → count → daily) with first-failure-wins reason code (D-03)
- [05-02]: D-02 V1 conservative cluster rule: directionally-aligned BTC/ETH/SOL/XRP counted as one cluster (D-03 + RESEARCH A3)
- [05-02]: D-03 Candidate risk ADDED to cluster/aggregate sums; candidate NOT counted in position count (Pitfall 6 lock)
- [05-02]: D-04 Open positions sorted by (symbol, position_side) before aggregation for deterministic iteration (Pitfall 4)
- [05-02]: D-05 TTL subtraction between UTC-aware datetimes only; boundary at exactly TTL is PASS, one second over is STALE_CONSTRAINTS (Pitfall 3)
- [05-02]: D-06 Daily state machine NORMAL → WARNING → DAILY_STOP with inclusive boundaries; DAILY_STOP blocks, WARNING passes with state reported
- [05-02]: D-07 Fail-closed on None daily_loss_quote, positions_reconciled=False, stale constraint snapshot (D-04)
- [05-02]: D-08 parameter_set values are ABSOLUTE quote amounts in check_portfolio; caller converts registry rates to absolute amounts

### Pending Todos

None yet.

### Blockers/Concerns

- Paper forward observation (Phase 7) is wall-clock bound (3–6 months) — dominates calendar regardless of code velocity
- OI history irrecoverable outside ~30-day window — OI collector must start in Phase 2 day one
- Algo-Order field details MEDIUM confidence — re-verify against current Binance docs before Phase 9 wiring
- ApprovalResult value set is a planner assumption (D-10) — user confirmation pending
- evaluate_risk currently passes absolute amounts directly; Phase-7+ caller must convert registry rates to absolute amounts before calling

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| Rate-to-absolute conversion | Phase-7+ caller converts registry rates to absolute amounts before calling check_portfolio | Deferred to Phase 7+ | 2026-09-25 | v0.3 |
| Enum promotion | setup_type, regime, order_role, side, position_side, order_type, time_in_force, event_type, entity_type | Deferred to Phase 4 | 2026-09-22 | v0.3 |
| trades table | Logical user-executed trade entity (DATA_MODEL §2.6) | Deferred to Phase 5 | 2026-09-22 | v0.3 |
| experiment_runs table | Backtest/research reproducibility (DATA_MODEL §2.12) | Deferred to Phase 6 | 2026-09-22 | v0.3 |
| Registry DB mirror | DB table mirroring registry rows for experiment-join queryability | Deferred to Phase 6 (files canonical) | 2026-09-22 | v0.3 |

## Session Continuity

Last session: 2026-09-25T16:00:00.000Z
Stopped at: Phase 5 plan 2 complete
Resume file: .planning/phases/06-backtest/06-01-PLAN.md
