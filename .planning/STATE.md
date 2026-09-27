---
gsd_state_version: "1.0"
milestone: v0.3
current_phase: 8
current_phase_name: Approval + Reconciliation Hardening
status: executing
stopped_at: Completed 08-01-PLAN.md
last_updated: "2026-09-27T11:51:54.489Z"
last_activity: 2026-09-27
last_activity_desc: Phase 8 execution started
state_head: 400e4d6eb1a21ba2bcdfe2b7fad89ada44f3db5c
progress:
  total_phases: 11
  completed_phases: 6
  total_plans: 34
  completed_plans: 30
milestone_name: milestone
---

<!-- STATE-MD-SCHEMA:END:frontmatter -->

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-19)

**Core value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.
**Current focus:** Phase 8 — Approval + Reconciliation Hardening

## Current Position

Phase: 8 (Approval + Reconciliation Hardening) — EXECUTING
Plan: 2 of 5
Status: Ready to execute
Last activity: 2026-09-27 — Phase 8 execution started

Progress: [████████░░░] 75%

## Performance Metrics

**Velocity:**

- Total plans completed: 9 (Phase 03 + Phase 05 plans 1+2 + Phase 06 plan 1)
- Average duration: ~14 min
- Total execution time: ~100 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 03 | 4 | 5 | ~12 min |
| 05 | 2 | 2 | ~25 min |
| 06 | 1 | 3 | ~15 min |
| 07.1 | 2 | - | - |

**Recent Trend:**

- Last 7 plans: 03-01 (tracer slice) — ~15 min, 03-02 (six entities) — ~10 min, 03-03 (registry hardening) — ~10 min, 03-04 (ORM mirror + mappers + migration) — ~15 min, 05-01 (risk tracer slice) — ~25 min, 05-02 (portfolio gates) — ~25 min, 06-01 (backtest simulator tracer slice) — ~15 min
- Trend: stable

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 06 P02 | 45min | 3 tasks | 12 files |
| Phase 06 P03 | 45min | 3 tasks | 7 files |
| Phase 07.1 P01 | ~15 min | 2 tasks | 9 files |
| Phase 07.1 P02 | ~10 min | 2 tasks | 4 files |
| Phase 07 P01 | ~45 min | 3 tasks | 10 files |
| Phase 07 P02 | ~30 min | 3 tasks | 8 files |
| Phase 08 P01 | ~15 min | 3 tasks | 7 files |

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
- [06-01]: D-05 src/backtest/ is dependency-free (stdlib + Decimal + src/core/_decimal.py only); no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic
- [06-01]: D-01 Invalidation gate uses bar direction (bearish bar for LONG, bullish bar for SHORT) since SL < bar.low ≤ bar.close makes bar.close < SL structurally impossible
- [06-01]: D-02 Expiry check uses fixture now_utc (backtest wall-clock), NOT bar.close_time_utc — a backtest running past expiry means the limit window closed without a fill
- [Phase 06]: [06-02] D-01 assemble() uses parameter_set.parameter_set_hash from registry (fail closed on UnregisteredParameterSet); experiment_id binds to registry's authoritative hash
- [Phase 06]: [06-02] D-02 universe_hash sorts symbols alphabetically before sha256_hex for input-order stability
- [Phase 06]: [06-02] D-03 Baselines are NEW TOML files (baseline-no-trade-v1.toml minimum_rr=100; baseline-simple-trend-v1.toml looser config); runners delegate to simulator.run with the new parameter_set_id
- [Phase 06]: [06-02] D-05 STRING_KEYS set added alongside INT_KEYS and DECIMAL_KEYS; three string-valued cost keys validated as non-empty strings; partial_fill_fraction classified as DECIMAL_KEYS
- [Phase 06]: [06-02] D-04 Baselines filter simulator output to filled trades only (entry_kind in {ENTRY_FILLED, PARTIAL_FILL}); REJECT records are risk-rejection outcomes, not filled trades
- [Phase 07.1]: [07.1-01] D-01 gate lives in assemble(); canonical-hash-to-hash compare against registry cost-key slice; CostModelBindingMismatch on inequality (distinct from ExperimentReproducibilityBroken)
- [Phase 07.1]: [07.1-01] D-02 keep both representations (registry TOML + cost dict); shared assertion helper reused by assemble() — comparison logic exists exactly once
- [Phase 07.1]: [07.1-01] D-04 six-field identity tuple byte-stable; gate only shrinks the set of assemblable inputs, never changes what a consistent input hashes to
- [Phase 07.1]: [07.1-01] D-03 fail closed with dedicated CostModelBindingMismatch exception; absent slice keys propagate as bare KeyError from build_cost_model
- [Phase 07.1]: [07.1-01] D-05 phase6 fixtures stay byte-identical (grandfathered); tests that call assemble() migrate to baseline-v3 (7-key set); new tests/fixtures/phase7.1/ binding fixtures
- [Phase 07.1]: [07.1-02] D-05 grandfather log in test module header documents phase6 audit verdict (8 missing-keys + 2 spelling); bare KeyError propagates from build_cost_model for missing slice keys (never translated, never skipped, never ExperimentReproducibilityBroken); comparison is hash-string only (never Decimal value equality)
- [Phase 07]: [07-01] D-01 paper loop is the realtime mirror of the backtest — identical evaluate→plan→evaluate_risk chain, no paper-local setup logic, no simplified sizing, no cost-free path
- [Phase 07]: [07-01] D-02 double closed-candle gate is structural (x=True AND close_time_utc <= now_utc), not a log warning; forming updates and future-close markers MUST NOT reach evaluate
- [Phase 07]: [07-01] D-03 feature-validity gate short-circuits the whole loop when either stream lacks EMA200 warmup; feed-freshness gate is per-event (not latched) so a fresh event after a stale one resumes evaluation without restart
- [Phase 07]: [07-01] D-04 SDK WS surface isolated to src/adapters/paper_ws.py; src/paper/loop.py imports nothing from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + Decimal + src/core/_decimal.py only
- [Phase 07]: [07-01] D-05 STALENESS_THRESHOLD_SECONDS=60 (1H cadence) and WARMUP_MIN_BARS=200 (EMA200) exported as module constants for tests and downstream consumers
- [Phase 07]: [07-02] D-01 resync drops forming candles (x=False or close_time_utc > now_utc) before the open_time_utc diff — never synthesizes; unrecoverable windows stay explicit gap records matching CollectorGap shape
- [Phase 07]: [07-02] D-02 24h server-initiated rotation triggers on_disconnect(scheduled=True) — NO reconnect attempt (WS still connected), only resubscribe + resync from last-seen close; only unsolicited drops get the bounded reconnect path
- [Phase 07]: [07-02] D-03 parity gate is a divergence tripwire — replay helper builds paper loop inputs from strategy_bars bar by bar; projection reduces both outputs to (signal_id, reason_code) tuples; any divergence is an engine incident fixed in the shared engine, never at the paper call site
- [Phase 07]: [07-02] D-04 prefix-invariance test guards D-02 determinism — verdict for bar N must depend only on bars [0..N]; appending a post-horizon bar must not change earlier verdicts
- [Phase 07]: [07-02] D-05 src/paper/resync.py and src/paper/supervisor.py import only stdlib + tenacity + structlog + sibling modules; no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic leaks
- [Phase 07]: [07-02] FLAGGED ASSUMPTION (PAPER-01 unclassified): bounded-retry ceilings (RESYNC_MAX_ATTEMPTS=7, RESYNC_MAX_DELAY_SECONDS=120, SUPERVISOR_MAX_ATTEMPTS=7, SUPERVISOR_MAX_DELAY_SECONDS=120) are module-level named constants; operator tunes them only before a soak epoch starts, never mid-epoch
- [Phase 07]: [07-04] D-04 frozen: pin_stream_epoch fails closed on CostModelBindingMismatch; check_registry_unchanged re-hashes without rewriting old pinned hashes; pinned hash string is append-only history (per epoch_id)
- [Phase 07]: [07-04] D-05 frozen: SIMULATE-notify is journal-first send-only with bounded tenacity retry (NOTIFY_MAX_ATTEMPTS=3, NOTIFY_MAX_DELAY_SECONDS=30); callbacks are inert labels (SIMULATE-recorded / SKIP (Phase 8)); never auto-approves on notification failure
- [Phase 07]: [07-04] Telegram isolation: only src/adapters/telegram_notify.py imports python-telegram-bot; src/paper/notify.py consumes a Protocol-typed TelegramBot with test-injected fake
- [Phase 07]: [07-04] FLAGGED ASSUMPTION (PAPER-03 unclassified): freeze-monitor tick cadence (hourly cron) and minimum-evidence signal-frequency gate are researcher-set values recorded in the soak log, not code defaults
- [Phase 07]: [07-04] BLOCKED-FOLLOW-UP: PaperWsAdapter + PaperSupervisor have no SDK connect path wired (0 live events in 30s); Wave 1/2 tests use injected fakes. Soak must NOT start until live WS smoke passes. Routed to executor as separate plan.
- [Phase 8]: [08-01] D-01 fixed gate order enforced: chat -> expiry -> plan-hash -> version/parameter-set -> token; chat gate runs BEFORE any state lookup (security-critical invariant)
- [Phase 8]: [08-01] D-02 token-hash is the idempotency key; raw token never persisted or logged; SHA-256 hex form stored on Approval.approval_token_hash
- [Phase 8]: [08-01] D-03 constant-time compare via hmac.compare_digest prevents timing attacks on token verification
- [Phase 8]: [08-01] D-04 expiry boundary inclusive: now_utc >= expiry_utc is expired; one second before expiry is still approvable
- [Phase 8]: [08-01] D-05 src/approval/ is dependency-free (stdlib + src/domain/* only); no telegram, binance_sdk, sqlalchemy, pydantic, polars imports; zero float( usage for money/qty/price fields

### Pending Todos

- WS-connect gap fix (PaperWsAdapter + PaperSupervisor SDK connect path proven live) — blocks soak start

### Blockers/Concerns

- Paper forward observation (Phase 7) is wall-clock bound (3–6 months) — dominates calendar regardless of code velocity
- OI history irrecoverable outside ~30-day window — OI collector must start in Phase 2 day one
- Algo-Order field details MEDIUM confidence — re-verify against current Binance docs before Phase 9 wiring
- ApprovalResult value set is a planner assumption (D-10) — user confirmation pending
- evaluate_risk currently passes absolute amounts directly; Phase-7+ caller must convert registry rates to absolute amounts before calling
- WS-connect gap (07-04 follow-up) blocks soak start; Phase 8 construction can proceed in parallel

### Roadmap Evolution

- Phase 07.1 inserted after Phase 7: Close gap: B1 registry-cost to backtest identity binding (URGENT)
- Phase 07.1 edited: edited fields: depends_on (Phase 7 -> Phase 6)

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

Last session: 2026-09-27T11:51:54.390Z
Stopped at: Completed 08-01-PLAN.md
Resume file: None
