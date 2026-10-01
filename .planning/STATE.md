---
gsd_state_version: "1.0"
milestone: v0.3
current_phase: "13.1"
current_phase_name: Deployment & CI
status: executing
stopped_at: Completed 13.1-08-PLAN.md
last_updated: "2026-10-01T07:27:22.167Z"
last_activity: 2026-10-01
last_activity_desc: Phase 13.1 execution started
state_head: fa31ab7e4a04856dd947d64d545e25723d390711
progress:
  total_phases: 29
  completed_phases: 3
  total_plans: 94
  completed_plans: 87
milestone_name: milestone
---

<!-- STATE-MD-SCHEMA:END:frontmatter -->

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-19)

**Core value:** Every trading decision is deterministic, reproducible, and explainable from market data plus a versioned strategy spec — no AI/LLM in the decision path.
**Current focus:** Phase 13.1 — Deployment & CI

## Current Position

Phase: 13.1 (Deployment & CI) — EXECUTING
Plan: 9 of 12
Status: Ready to execute
Last activity: 2026-10-01 — Phase 13.1 execution started

Progress: [█░░░░░░░░░] 11%

## Performance Metrics

**Velocity:**

- Total plans completed: 20 (Phase 03 + Phase 05 plans 1+2 + Phase 06 plan 1)
- Average duration: ~14 min
- Total execution time: ~100 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 03 | 4 | 5 | ~12 min |
| 05 | 2 | 2 | ~25 min |
| 06 | 1 | 3 | ~15 min |
| 07.1 | 2 | - | - |
| 12 | 11 | - | - |

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
| Phase 08 P03 | ~10 min | 2 tasks | 5 files |
| Phase 08 P04 | ~25 min | 3 tasks | 8 files |
| Phase 8 P2 | ~25 min | 3 tasks | 8 files |
| Phase 8 P05 | ~15 min | 2 tasks | 4 files |
| Phase 09 P04 | ~50min | 2 tasks | 11 files |
| Phase 10 P01 | 18min | 3 tasks | 23 files |
| Phase 10 P02 | 12 min | 2 tasks | 7 files |
| Phase 10 P03 | 12 min | 3 tasks | 8 files |
| Phase 10 P04 | 27min | 3 tasks | 14 files |
| Phase 10 P05 | 5 min | 3 tasks | 14 files |
| Phase 10 P06 | 11 min | 3 tasks | 8 files |
| Phase 10 P07 | 12 min | 3 tasks | 18 files |
| Phase 10 P08 | 12 min | 3 tasks | 6 files |
| Phase 10 P09 | 13 min | 3 tasks | 7 files |
| Phase 10 P10 | 14 min | 2 tasks | 6 files |
| Phase 10 P11 | 35 min | 3 tasks | 7 files |
| Phase 10 P12 | 13 min | 3 tasks | 6 files |
| Phase 11 P01 | 30 min | 3 tasks | 10 files |
| Phase 11 P02 | 25min | 3 tasks | 11 files |
| Phase 11 P03 | 20min | 2 tasks | 3 files |
| Phase 11 P04 | 25min | 3 tasks | 8 files |
| Phase 11 P06 | 30 min | 2 tasks | 6 files |
| Phase 11 P05 | 40min | 3 tasks | 7 files |
| Phase 11 P07 | 10 min | 3 tasks | 8 files |
| Phase 11 P08 | 35 min | 3 tasks | 4 files |
| Phase 12 P01 | 25 min | 2 tasks | 5 files |
| Phase 12 P02 | 35min | 3 tasks | 12 files |
| Phase 12 P03 | 35min | 2 tasks | 9 files |
| Phase 12 P04 | 25 min | 2 tasks | 15 files |
| Phase 12 P05 | 25 min | 3 tasks | 6 files |
| Phase 12 P06 | 25 min | 2 tasks | 6 files |
| Phase 12 P07 | 25min | 3 tasks | 19 files |
| Phase 12 P08 | 15min | 2 tasks | 3 files |
| Phase 12 P09 | 35min | 3 tasks | 9 files |
| Phase 12 P10 | 10min | 3 tasks | 2 files |
| Phase 12 P11 | 35min | 3 tasks | 6 files |
| Phase 13 P01 | 21 min | 3 tasks | 9 files |
| Phase 13 P02 | 15 min | 3 tasks | 8 files |
| Phase 13 P03 | 15 min | 2 tasks | 3 files |
| Phase 13 P04 | 20 min | 3 tasks | 8 files |
| Phase 13 P05 | 11 min | 3 tasks | 2 files |
| Phase 13 P06 | 12 min | 3 tasks | 2 files |
| Phase 13 P07 | 20 min | 3 tasks | 5 files |
| Phase 13 P09 | 30 min | 3 tasks | 4 files |
| Phase 13 P10 | 15min | 3 tasks | 3 files |
| Phase 13 P08 | 35 min | 3 tasks | 4 files |
| Phase 13 P11 | 11 min | 3 tasks | 9 files |
| Phase 13.1 P01 | 40 min | 2 tasks | 12 files |
| Phase 13.1 P02 | 20min | 2 tasks | 5 files |
| Phase 13.1 P03 | 45min | 3 tasks | 7 files |
| Phase 13.1 P04 | 70min | 3 tasks | 8 files |
| Phase 13.1 P05 | 95min | 3 tasks | 5 files |
| Phase 13.1 P06 | 60min | 2 tasks | 2 files |
| Phase 13.1 P07 | 45min | 2 tasks | 2 files |
| Phase 13.1 P08 | 45 min | 3 tasks | 5 files |

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
- [Phase 8]: [08-03] D-01 ROLE_CODES maps exactly the OrderRole vocabulary (ENTRY, STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2) to distinct 2-char codes (EN, SL, T1, T2); the table is the only place role-code literals appear
- [Phase 8]: [08-03] D-02 derive_client_order_id and derive_algo_client_id are pure functions of (plan_hash, role) using stdlib only — no float, no locale-dependent string conversion
- [Phase 8]: [08-03] D-03 Pinned ID shape: client_order_id = 'x-' (2) + plan_hash[:32] (32) + role_code (2) = 36 chars; algo_client_id = 'xa-' (3) + plan_hash[:31] (31) + role_code (2) = 36 chars
- [Phase 8]: [08-03] D-04 Charset is a strict subset of the Binance client-order-ID rule (<=36 chars, ASCII alnum + hyphen/underscore): [0-9a-f-] plus uppercase role codes
- [Phase 8]: [08-03] D-05 Unknown role raises ValueError with the canonical vocabulary listed in the message — no fallback code, no silent default
- [Phase 8]: [08-03] D-06 plan_hash slice is the first N hex chars of the canonical 64-char SHA-256 plan hash — deterministic across processes and Python versions
- [Phase 8]: [08-03] D-07 Retry/restart/replay determinism proven: same call twice, importlib.reload, and interleaving other plans all yield byte-identical IDs
- [Phase 8]: [08-04] D-01 Five divergence kinds: ORPHAN_PROTECTIVE (sweeper target), ENTRY_WITHOUT_PROTECTIVE (SAFE_MODE trigger, never swept), UNSYNCED_NORMAL, UNSYNCED_ALGO, UNSYNCED_POSITION (each drives SAFE_MODE without cancel)
- [Phase 8]: [08-04] D-02 ORPHAN_PROTECTIVE classification: local algo protective (SL/TP1/TP2) with no matching local position AND no exchange position — regardless of whether the algo still matches the exchange truth
- [Phase 8]: [08-04] D-03 Sweeper requires authoritative position-zero verification (T-8-30): two consecutive zero reads from the position_verifier callable; a single non-zero read blocks the cancel
- [Phase 8]: [08-04] D-04 Sweeper uses query-by-ID-first posture (T-8-32): query_algo_order_by_client probe before cancel; not-found probe is treated as a successful prior sweep
- [Phase 8]: [08-04] D-05 Sweeper journals pre-image BEFORE the cancel call and post-image AFTER (D-05 extended journal-first ordering); the audit trail is the safety net
- [Phase 8]: [08-04] D-06 SAFE_MODE enters on any divergence (idempotent re-entry); exits only on a fresh clean three-source compare PLUS a journaled SAFE_MODE_EXIT event (Pitfall 4)
- [Phase 8]: [08-04] D-07 SAFE_MODE_TICK_SECONDS=60 with operator-tunable-before-soak semantics (FLAGGED ASSUMPTION, RECON-01 unclassified); 60s per RESEARCH A2
- [Phase 8]: [08-04] D-08 Adapter extension is the only module importing the Binance SDK for reconciliation calls; src/reconcile/ consumes Protocol-typed surfaces
- [Phase 8]: [08-04] D-09 SDK 17.3.1 -> 17.4.0 delta (per RESEARCH Open Question 2 closed): no public REST method-signature change in any of the seven reconciler methods; ALGO_UPDATE.o.rm field semantics change is WS-side and out of scope
- [Phase 8]: [08-04] D-10 Bounded-tenacity cancel ceilings (RECONCILER_CANCEL_MAX_ATTEMPTS=3, RECONCILER_CANCEL_MAX_DELAY_SECONDS=30) mirror the notify/resync precedent; transient-only retry filter
- [Phase 8]: [08-04] D-11 Already-canceled-as-success posture: SDK error code -2011 (UNKNOWN_ORDER) on cancel is treated as success because the post-condition is satisfied
- [Phase 8]: [08-04] D-12 Zero-amount positions filtered out of snapshot_positions: Binance semantics is position_amt == 0 means no position
- [Phase 8]: [08-02] D-08-02-01 format_approve is PTB-free and mirrors format_simulate posture; lives in telegram_notify.py so paper-core can reuse it without adapter violation
- [Phase 8]: [08-02] D-08-02-06 receiver persists ShortIdMappingRow in the SAME transaction as the Approval row transition via injected save_atomic(approval, mapping); replay paths pass mapping=None
- [Phase 8]: [08-02] D-08-02-10 LIVE-TAP GATE PENDING: TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID not provisioned in this environment; operator must run real APPROVE + SKIP tap + unknown-chat rejection before plan 08-02 can be marked complete
- [Phase 8]: [08-05] D-01 Canonical 8-drill vocabulary pinned in DRILL_NAMES tuple (unprotected, orphan, duplicate, api_down, stale_feed, db_failure, manual_close, restore); tuple order is part of the acceptance contract
- [Phase 8]: [08-05] D-02 Drill harness drives 08-01 approval core, 08-02 receiver seam, and 08-04 reconciler/sweeper/SAFE_MODE through Protocol-typed surfaces; tests inject fakes; no Binance SDK or PTB leakage
- [Phase 8]: [08-05] D-03 Double-run determinism: caller-supplied now_utc sequence (never wall-clock); repeat runs produce byte-identical ordered outcome names and payloads
- [Phase 8]: [08-05] D-04 SAFE_MODE exit rehearsed only through the restore drill (Pitfall 4: a boolean flip without both a clean compare AND a journaled restore event is rejected)
- [Phase 09]: [09-04] health.py: ten fail-closed probes journal HEALTH_CHECK; any FAIL blocks enablement via run_health_checks aggregate
- [Phase 09]: [09-04] require_protective_confirmation is single source of truth for SL/TP1/TP2 confirmed check; composes with SafeModeController on any gap, never places rescue protection
- [Phase 09]: [09-04] attach_protectives_to_fill places SL then TP1 then TP2 in fixed order; unconfirmed leg halts immediately with zero rescue placement
- [Phase 09]: [09-04] LIVE5_SYMBOLS scope guard raises ValueError before any adapter call across execute_approved_plan, attach, expiry, cancel, and emergency-close paths
- [Phase 09]: [09-04] Task 3 (testnet plus credential plus LIVE-TAP GATE) is gate=blocking-human — plan BLOCKED pending operator attestation; no live order exists
- [Phase 10]: Evidence kinds are never pooled and every TradeOutcome carries strategy_version + parameter_set_hash (analytics core types)
- [Phase 10]: Estimate carries n and n_valued; interval_absent is an explicit marker when n_valued < 2, otherwise a seeded Phase-6 stationary-block-bootstrap interval
- [Phase 10]: ExcursionSection seed ordinals: measures 0-6 in EXCURSION_MEASURES order, diagnostics 7-9; per_trade sorted by trade_id, bootstrap input in (exit_time, trade_id) order
- [Phase 10]: Analytics reuses Phase-6 private report helpers intentionally (RESEARCH P7), guarded by fixture digests; time arithmetic uses integer microseconds, never total_seconds
- [Phase 10]: D030: D013 firing rule (>=3 independently specified families AND >=6 calendar months since freeze AND none passing) recorded as new decision + protocol v1.0.1 clarification; Status/Frozen-on/D029 untouched; amendment class flagged for user confirmation
- [Phase 10]: KillGateState (WITHIN_BUDGET, PASSING_CANDIDATE, INSUFFICIENT_EDGE) lives in src/domain/enums.py, GLOSSARY 8.2 canonical
- [Phase 10]: 10-03: approved_at_utc for live records is set only for APPROVED approvals; SKIPPED/EXPIRED acted_at is never an approval time — Prevents mislabelled skip times polluting DELIVERY_TO_APPROVED/SIGNAL_TO_APPROVED legs (T-10-07)
- [Phase 10]: 10-03: paper sections carry synthetic_lag_seconds (imported APPROVAL_DELAY_LAG_SECONDS); SIGNAL_TO_SEEN is always INCOMPLETE(NO_SEEN_TIMESTAMP); Approval.requested_at_utc is a delivery-request proxy — No seen timestamp is journaled and paper approval time is a constant; honesty over imputation (D-02, RESEARCH P1/P2)
- [Phase 10]: 10-04: slice time bases pinned - month/quarter from exit time, session from entry-time UTC bands ASIA 00-08/EUROPE 08-16/US 16-24; missing basis time -> INCOMPLETE, absent tag -> UNKNOWN (D-02, flagged A1/A4)
- [Phase 10]: 10-04: R-valued requires R and an exit time; low_n is a display flag on n_r_valued only, never an acceptance gate; NO_TRADE reason-to-category mapping is a documented assumption with UNMAPPED counted
- [Phase 10]: 10-05: kill-gate decision checkpoint auto-approved (pre-approved by locked CONTEXT D-03, option-deterministic-journaled); KILL_GATE_EVALUATION contract fixed one-way: 24-key constant payload, id prefix kill_gate, entity KILL_GATE_D013, reopen/sticky fields present from plan 05 — Only counted families (independent, TESTED_*, decided_at >= cycle start) drive the verdict; TESTED_* is constructible only from a recorded decision_ref plus Development/Validation experiment ids; evaluator never compares metrics to thresholds
- [Phase 10]: 10-06: LIVE_NET_PNL_SEMANTICS_VERIFIED stays False (Binance realizedPnl/commission semantics not verifiable from official docs on 2026-09-29); live R is INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS) until a human records a docs citation — Project rule: exchange semantics never taken from memory; fail closed
- [Phase 10]: 10-06: approval-delay reports are descriptive only; delay buckets and measured_delay are LIVE-only, PAPER keeps the SYNTHETIC LAG label and APPROVAL_DELAY_LAG_SECONDS is unchanged — D-02 / RESEARCH P2, Open Question 4
- [Phase 10]: 10-07: Post-reset kill-gate semantics (FLAGGED PLANNER DECISION, D013 silent): cycle clock restarts at the latest valid reset time, only decisions dated on/after it count, reopening decision_ref/operator recorded; INSUFFICIENT_EDGE sticky until an explicit human KILL_GATE_QUESTION_APPROVED after the latest terminal — D-03 never auto-clears; evaluator only reads resets, never writes or infers them
- [Phase 10]: 10-07: enable() requires an evaluated kill_gate_state and refuses INSUFFICIENT_EDGE/non-KillGateState before any journal write; registration blocked in CI via docs/research/kill_gate_decisions.json recorded_terminal tripwire; enable journal payload unchanged — Phase 9 D-04 + Phase 10 D-03 fail-closed; CI cannot read the journal
- [Phase 10]: 10-08: ReportInputs.clock is required; provenance keeps per-kind identity (by_evidence) and tags experiments by evidence slot; family gate facts for unknown families raise; posture tie ordering follows the plan total key (ENABLED after DISABLED at the same instant, display-only)
- [Phase 10]: 10-09: family sheet hash normalizes CRLF to LF so digests match the committed blob across checkouts; unknown CANDIDATE parameter_set_hashes are listed in unknown_experiment_ids, never guessed onto a family; the only analytics write is one ON CONFLICT DO NOTHING KILL_GATE_EVALUATION append — Determinism across Windows autocrlf and CI checkouts; fail-closed family mapping (D-03); SELECT-only reader (T-10-28)
- [Phase 10]: 10-10: Section 1 uses numbered H3 blocks (1.1 budget ... 1.9 enablement effect); md_cell also escapes backslash and drops Unicode format/control characters; golden pinned with a -text gitattribute
- [Phase 10]: 10-10: SECTION_TITLES lives in render_common and is re-exported from render; requirements JRN-01/GOV-01 left unmarked (ready-ids 0/2)
- [Phase 10]: 10-11: Live-5 line built from sorted LIVE5_SYMBOLS (single source) instead of a second hard-coded order
- [Phase 10]: 10-11: verify_render recomputes the report digest only when given the report; without it it checks the Markdown SHA-256 and header/sidecar digest agreement
- [Phase 10]: 10-11: Telegram pointer is a formatter only; no send wired (notify Protocol is inline-keyboard only, plain-text send deferred per D-04)
- [Phase 10]: 10-12: report CLI is read-only by construction; the only write is one guarded, idempotent KILL_GATE_EVALUATION append via --record after both files exist — D-03/D-05: journal append stays an explicit separate step; ON CONFLICT DO NOTHING on the content-hash id makes replays no-ops
- [Phase 10]: 10-12: database failures surface as exception type names only; DATABASE_URL is read once and passed only to the session factory — RESEARCH V7: no credential or request text in stdout, stderr, reports or sidecars
- [Phase 10]: 10-12: CLI runs asyncio on SelectorEventLoop on Windows and disposes the engine per run — psycopg async cannot use the Proactor loop; read and record use separate asyncio.run calls
- [Phase 11]: D043: research protocol v1.1.0 frozen with D032 pre-registration (100/30 trade floor, N=25 Holm-Bonferroni per family, last-20% single-use holdout); Frozen-on unchanged so the D013 clock is not restarted
- [Phase 11]: 11-02: working_type is a closed-set registry string key (MARK_PRICE/CONTRACT_PRICE), outside COST_KEYS; D036-D038 delivered as five new v3.0.0 sets, old params files byte-locked and all 15 sets pinned
- [Phase 11]: 11-03: research-universe manifest is DRAFT with no symbols under docs/research/universe; Phase 13 freezes it with a sha256_hex content hash over sorted symbols
- [Phase 11]: 11-04: liquidation buffer stays a registry parameter (value chosen in Phase 22); canonical quantization order lives on one labelled line in RISK_MANAGEMENT s11 (D031)
- [Phase 11]: 11-06: TradingView cannot sign requests; docs describe secret URL path + source-IP allow-list + 3s ack + dedupe + normalise + 2FA (F-052); V1 has no webhook endpoint
- [Phase 11]: 11-06: single canonical quantization order restated by pointer in PROJECT.md and AGENTS.md (D031); generated AGENTS.md rows guarded by drift gates AU-03/AU-05
- [Phase 11]: 11-05: 200 conditional-order limit documented account-wide from the dated change-log (2025-12-29); pages not retrievable are registered as not fetched and keep verify markers
- [Phase 11]: 11-07: GLOSSARY canonical reason codes are the 17 code-referenced plus reserved INSUFFICIENT_MARGIN; five synonyms are deprecated aliases kept in the enum until the Phase 12 cleanup — D-15: no rename in Phase 11; gates GL-01..GL-06 tie the glossary to src/ and the enum
- [Phase 11]: 11-07: 13 new requirement IDs registered (mapped to phases 13-26, Pending); D044 records the alignment and follow-ups, D045 records exclusions (trades, feature_snapshots, experiment_runs not built; no application-level secret encryption in V1) — D-16: silent drops not allowed; F-128 covered by OPS-02
- [Phase 12]: 12-01: RejectionReason reduced to 20 codes (STOP_TOO_TIGHT, COST_TO_RISK_EXCEEDED added; five aliases retired, GLOSSARY 9.2 is a removal record; GL-01/GL-03 keep them out)
- [Phase 12]: 12-02: Phase 12 cost-guard keys are optional registry keys; exit_slippage_rate stays outside the 7-key COST_KEYS so existing cost_model_hash values do not move; five v4.0.0 sets pinned and gated by PA-07
- [Phase 12]: 12-03: cost_model_hash canonicalizes numeric values to plain normalized text (D-15, D047); exit_slippage_rate joins the hash by presence, COST_KEYS stays 7 keys; legacy models refused for sizing
- [Phase 12]: 12-04: Phase 6 fixtures regenerated with BAR_HALF_RANGE 0.80 (stops about 1.1 percent) on baseline-v5 / v3 sets; guard clearance pre-flight uses independent literal arithmetic
- [Phase 12]: 12-05: adapter keeps its own 0.01 commission-rate ceiling (imports nothing from src); commissionRate SOURCES row stays MEDIUM (official page not read directly)
- [Phase 12]: 12-06: risk sizing entry is the adverse zone edge (LONG entry_max, SHORT entry_min); zone mid stays the quantizer notional reference (supersedes Phase 5 D-02 for sizing; DECISIONS D046 by 12-11)
- [Phase 12]: 12-07: Phase 5 portfolio test helper runs shared size_and_quantize; candidate risks hand-derived in DERIVATIONS.md
- [Phase 12]: 12-08: legacy modeled_costs_per_unit key rejected explicitly in the live cost-rate gate; PARAMETER fee source is NO_TRADE UNCERTAIN_ACCOUNT_STATE before evaluate_risk
- [Phase 12]: 12-09: EOD exits use exit_slippage_rate (market-style close, D046 assumption A2); TP1 uses expected_slippage; unknown exit_kind refused
- [Phase 12]: 12-09: guard rates read at the risk stage in both modes via guard_rates_from_params (legacy sets fail closed, paper fixtures that never reach risk keep legacy sets)
- [Phase 12]: 12-10: property test uses zero loss tolerance; vacuity proof kept as a permanent harness test
- [Phase 12]: D046-D048 recorded; max_cost_to_risk 0.15 implies ~0.79 percent min stop, ratification pending
- [Phase 13]: 13-01: collector universe comes from docs/research/universe/collect-list-v1.toml; any list defect exits 2 (healthcheck 1) with no live-5 fallback
- [Phase 13]: 13-01: collect list is an operational input (no FROZEN semantics, no hash, not under params/); proposer keeps only TRADING PERPETUAL USDT, ranks by Decimal quoteVolume with symbol tie-break
- [Phase 13]: 13-02: backfill publishes only whole closed UTC days (effective end = min(end_ms, current UTC day start)); partial days held and counted, terminal_end only for a closed past end
- [Phase 13]: 13-02: Parquet publish is atomic (same-dir tmp, fsync, exists check, bounded os.replace retry); zero-trade bars accepted as telemetry; more than 8 fractional digits or non-finite Decimal is a structural reject
- [Phase 13]: 13-03: supervisor verification backfill skips pairs whose first pass raised; last-close cursor is monotonic via lock-guarded _advance_last_close gating WS dispatch and backfill
- [Phase 13]: Mark-price klines are a separate immutable dataset under data/raw/dataset=mark_klines (invisible to candles_v1, inside the backup root); rows carry price_tick_count and no volume or trade_count (D-11, D-29)
- [Phase 13]: Paginator is dataset-generic via DatasetSpec (TRADE_DATASET default, MARK_DATASET); CursorStore.dataset namespaces cursor files and a mismatched cursor store is refused
- [Phase 13]: Only an empty markPrice string maps to None in historical funding rows; malformed values still raise; deliveryDate exposed as SymbolFilters.delivery_date_ms with no migration (D-26)
- [Phase 13]: 13-05: archive CSV header accepted only as exactly open_time; both open_time and close_time must be 13-digit ms (fail closed)
- [Phase 13]: 13-05: checksum 404 disambiguated by probing zip status only (zip 404 -> ArchiveNotFound, zip 200 -> ArchiveChecksumMissing); monthly-404 falls back to daily zips, missing days skipped never interpolated
- [Phase 13]: 13-06: funding-history walk treats end_ms as inclusive (cursor <= end_ms); a page with no forward progress stops the symbol with a warning
- [Phase 13]: 13-06: clock probe is warn-only (>1000 ms warns, failure logs and returns None); fail-closed clock checks stay Phase 18, chrony Phase 13.1
- [Phase 13]: 13-07: backfill windows are per (dataset, symbol, interval); CLI calls backfill_universe once per (dataset, interval) with the window start as symbol floor and window end as symbol cap; mark windows copy trade windows
- [Phase 13]: 13-07: symbol absent from exchangeInfo or non-TRADING without deliveryDate gets DELIVERY_UNKNOWN and no window (fail closed); only the 13-08 archive fallback can bound it
- [Phase 13]: 13-07: refresh_symbol_metadata raises MetadataWidthError (ValueError) for universe rows with contract_type/status over 16 chars; CLI prints exception type names only, plus width-error message (symbol and field)
- [Phase 13]: 13-09: dataset_id = sha256 over sorted posix-relative path + file-bytes sha256 of exactly the files read; re-written datasets are new datasets — Reproducible experiment identity (BKTS-02, D-18); byte changes after a Polars upgrade must be visible
- [Phase 13]: 13-09: unresolved gap defined once in coverage.gap_ranges_for_files; builder fails closed (CaseInputGapError), allow_gaps recorded on the output — D-19: never pad or interpolate; acknowledged holes stay visible with the dataset
- [Phase 13]: [13-10] Freeze report proposal_sha256 covers the full report body (candidates, ranking, unrankable, availability), not only the ranking
- [Phase 13]: [13-10] Only -1121 switches REST to the archive; rate limits retry then fail the run; other REST errors fail closed; archive symbols listed with another contract type in exchangeInfo (TRADIFI) are never readmitted
- [Phase 13]: [13-10] Archive-only proposed symbols have no mark source (REST only): they stay proposed and are flagged UNAVAILABLE in the review for the operator (13-12)
- [Phase 13]: 13-08: sufficiency report checks data depth only; TRADE_FLOOR_NOTE states the D043 floor is unmeasurable until the Phase 14 simulator; exit 3 only for NOT_BACKFILLED, GAP, UNAVAILABLE
- [Phase 13]: 13-08: archive fallback is lazy per symbol (REST -1121 or not in exchangeInfo), mark only from REST, provenance persisted in <cursor-root>/_sources.json; archive-capped windows trimmed to the last archived bar in the report
- [Phase 13]: 13-08: 1m coverage printed per protocol split block on the 1h/4h timeline; extending 1m beyond 12 months stays a user decision (D-21)
- [Phase 13]: D049 records Phase 13 data foundation; case-input builder lives in src/data/case_input.py (D-22 supersedes D-17); 1m depth stays 12 months pending the sufficiency report (D-21)
- [Phase 13]: Decision-alignment requirements gate maps OPS-06 to Phase 13.1 (string phases); Phase 13 exchange facts recorded MEDIUM where only SDK docstring or live probe was available
- [Phase 13.1]: 13.1-01: ruff format repo-wide in own commit; src/risk/portfolio.py F841 per-file ignore (risk code untouched); docker marker + TRADING_CI_STRICT-aware infra_skip
- [Phase 13.1]: 13.1-03: compose project name trading and runtime UID 10001 fixed; ops-image postgresql-client-17 floats within major 17 (sole exception to D-05)
- [Phase 13.1]: 13.1-04: structlog output becomes JSON after configure_logging(); redaction is value-based (env names containing PASSWORD/SECRET/TOKEN/API_KEY/ACCESS_KEY/CRYPT/PRIVATE, length >= 8) plus shape and key-name rules; alembic db-upgrade intentionally not wired
- [Phase 13.1]: [13.1-06] restore order verify -> checks -> pg_restore -> Parquet copy -> alembic upgrade head; all refusals precede the first destructive step; password only via PGPASSWORD
- [Phase 13.1]: 13.1-07: cutover report exit 2 covers all input/runtime failures; gap-measurement errors cannot hide proven data loss (exit 1)
- [Phase 13.1]: 13.1-08: upload order is parquet, pg.dump, manifest.json, cryptcheck so a snapshot is complete only after its dependencies exist; retention counts periods that have a snapshot; --init-remote also requires an empty raw bucket

### Pending Todos

- WS-connect gap fix (PaperWsAdapter + PaperSupervisor SDK connect path proven live) — blocks soak start

### Blockers/Concerns

- Paper forward observation (Phase 7) is wall-clock bound (3–6 months) — dominates calendar regardless of code velocity
- OI history irrecoverable outside ~30-day window — OI collector must start in Phase 2 day one
- Algo-Order field details MEDIUM confidence — re-verify against current Binance docs before Phase 9 wiring
- ApprovalResult value set is a planner assumption (D-10) — user confirmation pending
- evaluate_risk currently passes absolute amounts directly; Phase-7+ caller must convert registry rates to absolute amounts before calling
- WS-connect gap (07-04 follow-up) blocks soak start; Phase 8 construction can proceed in parallel
- 08-02 LIVE-TAP GATE: TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID must be provisioned and a real APPROVE/SKIP tap + unknown-chat rejection must be operator-confirmed before plan 08-02 can be marked status: complete (currently halted)
- Phase 09 Plan 04 task 3 (testnet rehearsal plus credential provisioning plus LIVE-TAP clearance GATE) is gate=blocking-human and cannot be executed or fabricated by the executor — awaiting operator attestation with real testnet order ids, RESEARCH A1 verdict, credential provisioning confirmation, and Telegram APPROVE/SKIP/unknown-chat tap evidence

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260930-bku | Record user-approved audit decisions D031-D039 in docs/DECISIONS.md | 2026-09-30 | c63d507 | [260930-bku-record-user-approved-audit-decisions-d03](./quick/260930-bku-record-user-approved-audit-decisions-d03/) |
| 260930-bvi | Import deep-audit report into .planning/audits and re-plan roadmap phases 11-26 (stay in v0.3) | 2026-09-30 | d190855 | [260930-bvi-import-deep-audit-report-and-re-plan-roa](./quick/260930-bvi-import-deep-audit-report-and-re-plan-roa/) |
| 260930-cgi | Add D040 safe release path (SHADOW-DEMO-CANARY-LIVE) and D041 two-step Telegram confirm; insert Phase 25 demo test campaign | 2026-09-30 | 7a05679 | [260930-cgi-add-safe-release-path-and-two-step-teleg](./quick/260930-cgi-add-safe-release-path-and-two-step-teleg/) |
| 260930-d0b | Record D042 single-VPS deployment; pull VPS hardening + collector deployment into Phase 13 | 2026-09-30 | 2660fb6 | [260930-d0b-record-single-vps-deployment-decision-d0](./quick/260930-d0b-record-single-vps-deployment-decision-d0/) |

### Roadmap Evolution

- Phase 07.1 inserted after Phase 7: Close gap: B1 registry-cost to backtest identity binding (URGENT)
- Phase 07.1 edited: edited fields: depends_on (Phase 7 -> Phase 6)
- Phase 13.1 inserted after Phase 13: Deployment & CI: CI pipeline, image pinning, bootstrap/migrate scripts, provider-portable backups; VPS provisioning deferred

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

Last session: 2026-10-01T07:27:21.900Z
Stopped at: Completed 13.1-08-PLAN.md
Resume file: None
