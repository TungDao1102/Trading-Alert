# Phase 4: Pure Core (Feature + Strategy + Planner) - Research

**Researched:** 2026-09-23
**Domain:** Deterministic trading-strategy core — pure-Python feature engine, pure strategy function, trade planner
**Confidence:** HIGH (in-repo contracts verified by Read; indicator math cross-checked across three independent implementations; only formula-choice details remain assumed)

## Summary

Phase 4 fills the Phase-3 scaffolding with real behavior: closed candles in, deterministic setups out. The work splits into three pure components inside a new dependency-free `src/core/` package — a feature engine (EMA/ATR/swing/zones from closed candles only, per-feature validity flags), a pure strategy function (`evaluate(snapshot, account_state, strategy_version, parameter_set) -> NO_TRADE | SETUP`), and a trade planner that emits one fully-populated `TradePlan` per setup with entry zone, SL, TP1/TP2, invalidation, expiry, expected RR, and plan hash.

All output contracts already exist and are frozen: `Signal` (`src/domain/signal.py`), `TradePlan` (`src/domain/trade_plan.py`), `make_signal_id`/`derive_child_id` (`src/domain/ids.py`), `sha256_hex` canonical hashing (`src/domain/canonical.py`), the TOML registry with closed `STRATEGY_KEYS` whitelist (`src/domain/registry.py`), and four determinism test suites with mechanism-only placeholders awaiting real expectations (`tests/test_no_lookahead.py`, `tests/test_prefix_invariance.py`, `tests/test_candle_close_timing.py`, `tests/test_domain_boundary.py` plus `tests/test_domain_no_float.py`). The planner's job is therefore mostly *wiring verified contracts together*, not inventing new ones.

The two genuine research risks are (1) the EMA/ATR smoothing conventions (TA-Lib `α=2/(n+1)` SMA-seeded EMA vs Wilder `α=1/n` SMA-seeded ATR — confusing them silently changes every downstream number) and (2) Decimal division precision inside a stdlib-only core (default context `prec=28` with `ROUND_HALF_EVEN` must never leak into hashed/compared values; use explicit `localcontext` or integer-ratio arithmetic where determinism matters). Both are addressed below with cited formulas and code patterns.

**Primary recommendation:** Implement tracer-first (`trend-pullback/baseline-v1.toml` end-to-end: features → strategy → planner → golden fixtures green), reusing `ids`/`canonical`/`registry` verbatim, with EMA(20/50/200) + ATR(14) + swing/zone features in stdlib+Decimal only, per-feature `valid/reason_code` gates, and the full TradePlan contract including `quantization_decision="DEFERRED_TO_RISK"` estimates — then add `breakout-retest` and `range-mr` as parallel slices on the same harness.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** V1 feature set is minimal and registry-driven: EMA(20/50/200), ATR(14), swing high/low over `swing_lookback`, support/resistance zones from `zone_tolerance_atr`. No OI/funding features in V1 (REFN-02/REFN-03 stay deferred); no 15M refinement (REFN-01 deferred). Feature code lives in a new pure package `src/core/` (e.g. `features.py`), importing NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + `Decimal` only, matching the Phase-3 D-01 domain purity precedent. — **Reversibility:** costly — feature names/semantics enter fixtures, registry-adjacent docs, and backtest parity.
- **D-02:** Input is closed-candle sequences only (list of frozen candle dataclasses / validated dicts sourced from Parquet rows via an adapter edge); the engine NEVER resamples, forward-fills, or reads an unclosed/in-progress candle. Multi-timeframe inputs (1H setup + 4H context, 1m reserved for Phase 6 intrabar) arrive as separate closed sequences; 4H context computed independently, never interpolated into 1H bars. — **Reversibility:** one-way — lookahead violations baked into fixtures would poison backtest evidence.
- **D-03:** Per-feature validity flags: every feature output carries `valid: bool` + `reason_code` (e.g. `WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`). Long-warm-up features (EMA200-4H ≈ 800h ≈ 33+ days of 4H history) report invalid until history suffices; the strategy treats any required-feature-invalid as NO_TRADE with reason code, never NaN/partial propagation. A whole-bar `features_valid` summary gates setup detection. — **Reversibility:** reversible — reason-code vocabulary grows additively.
- **D-04:** Gap policy inherits Phase-2 D-09 flag-never-fabricate: missing candles produce explicit gaps; features spanning a gap report invalid (or degrade per documented rule, never synthesize). Quality rejects (duplicate timestamps, OHLC violations, regressions) fail closed before features compute. — **Reversibility:** reversible — gap-handling refinements are additive rules.
- **D-05:** Tracer-first rollout: implement `trend-pullback/baseline-v1.toml` (the only registered set) end-to-end first (features → strategy → planner → golden fixtures green), then add `breakout-retest` and `range-mr` as parallel slices reusing the same harness. All three families land in Phase 4 as hypotheses; planner/researcher must NOT declare a winner (Phase-1 D-08, roadmap D012). New parameter keys per family extend the Phase-3 `STRATEGY_KEYS` whitelist via reviewed registry change, never ambient config. — **Reversibility:** one-way — published strategy versions + parameter hashes are permanent references.
- **D-06:** Promote deferred string fields to Enums now (closes Phase-3 deferred item): `direction` (LONG/SHORT), `setup_type` (per-family setup names), `source_timeframe`, plus planner `entry_model`/`order_role` and quantization `quantization_decision` vocabulary, in `src/domain/enums.py` with GLOSSARY-consistent names. `event_type`/`entity_type` (JournalEvent) and execution-side enums (`side`, `position_side`, `order_type`, `time_in_force`) promote only where Phase 4 constructs them; execution-lifecycle values stay Phase 8/9. Unknown values remain load-time errors. — **Reversibility:** costly — enum names persist in stored rows, fixtures, and Telegram payloads.
- **D-07:** Strategy is a pure function `evaluate(snapshot, account_state, strategy_version, parameter_set) -> NO_TRADE | SETUP(Signal fields)` with zero I/O, zero clock reads (timestamps passed in), zero randomness; `SignalId` via existing `ids.make_signal_id` and `detected_at_utc = source_candle_close_utc` (candle-close timing). Prefix-invariance and no-lookahead suites extend Phase-3 scaffolding with real family expectations. — **Reversibility:** one-way — SignalId inputs are stored in journal/experiment records forever.
- **D-08:** Every SETUP produces exactly one TradePlan filling the existing `src/domain/trade_plan.py` shape: entry zone `[entry_min_price, entry_max_price]` from `entry_buffer_atr`, `stop_loss_price` from `sl_buffer_atr`, `take_profit_json` with TP1 at `minimum_rr` and TP2 extension, `expected_rr_json` with per-TP RR, `invalidation_rule_json` (structure-break + candle-close basis), `expiry_utc = source_close + signal_expiry_hours`, `plan_hash` = SHA256 over canonical JSON of (signal_id + entry + SL + TPs + invalidation + expiry), mirroring the D-04 canonical-hash discipline. RR below `minimum_rr` → NO_TRADE with reason code, never a downgraded plan. — **Reversibility:** one-way — plan hashes are approval-bound in Phase 8.
- **D-09:** Quantization fields (`suggested_quantity`, `quantity_before/after_rounding`, `quantization_decision`, `risk_rate`, `risk_budget`) are populated with Decimal planner-side estimates for shape completeness, but exchange rounding/minimums enforcement stays Phase 5. Planner NEVER floor/round-up against stepSize — it records pre-risk quantities and marks `quantization_decision = "DEFERRED_TO_RISK"` (or Enum equivalent) so Phase 5 owns identical-everywhere math. — **Reversibility:** reversible — Phase 5 refines values without breaking the plan shape.
- **D-10:** `src/core/` (features, strategy, planner) is dependency-free: no Polars/pandas/NumPy/SciPy imports, no Binance SDK types, no SQLAlchemy/Pydantic, no `float` anywhere (extend Phase-3 AST no-`float(` guards + mypy strict), `Decimal` for all price/qty/RR arithmetic, UTC `datetime` internally. Adapters at the edges convert Parquet/registry decimals in and fixtures out. Deterministic ordering everywhere (sorted keys, fixed iteration order); no dict-order/wall-clock dependence. — **Reversibility:** costly — purity violations leak into every consumer's test story.

### the agent's Discretion
- User runs `--auto` (fully autonomous): all six gray areas auto-resolved to recommended defaults with no interactive prompts.
- Exact file layout inside `src/core/`, fixture CSV/JSON layout under `tests/fixtures/phase4/`, per-family parameter key additions to `STRATEGY_KEYS`, TP2 extension rule details, invalidation JSON schema, reason-code vocabulary, and plan slicing are at the planner/researcher discretion, provided D-01–D-10 semantics hold.
- Whether the three families land as 3 plans or tracer+2 slices is at the planner's discretion; tracer must stay first.

### Deferred Ideas (OUT OF SCOPE)
- Sizing/quantization enforcement → Phase 5 (D-09 defers exchange rounding/minimums; NO_TRADE-preferred-over-round-up stays Phase 5).
- Backtest intrabar/SL-first/costs engine → Phase 6; WS/paper loop → Phase 7; Telegram approval + reconciliation/SAFE_MODE → Phase 8; live Algo exits → Phase 9.
- OI/funding as strategy features (REFN-02/REFN-03), 15M entry refinement (REFN-01), correlation model (REFN-04), extra families (REFN-05) → v2 requirements, not Phase 4.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRAT-01 | Feature engine computes deterministic indicators/structure/zones from closed candles only, with warm-up gates (e.g. EMA200-4H invalid until history suffices) | EMA/ATR closed-form recurrences + SMA-seed convention (§Code Examples, [CITED]); per-feature validity-flag pattern (§Architecture Patterns); warm-up table (EMA200-4H ≈ 800 bars) |
| STRAT-02 | Strategy engine is a pure function (market snapshot + account state + strategy version + config → NO_TRADE or SETUP) emitting deterministic SignalIds | `make_signal_id` input tuple verified (§Standard Stack); pure-function discipline + prefix-invariance/no-lookahead extension plan (§Pitfalls, §Validation Architecture) |
| STRAT-03 | Trade planner translates each valid setup into entry zone, SL, TP(s), invalidation, expiry, expected RR, and plan hash | TradePlan field contract verified 1:1 (§Standard Stack); ATR-buffer planner math + plan-hash construction (§Code Examples); RR-gate → NO_TRADE rule |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- **Determinism:** same market snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs.
- **No-AI core:** LLM never decides direction/entry/SL/TP/size/risk/parameters/signal-validity.
- **Quantization:** floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject → NO_TRADE preferred over round-up; identical logic backtest/paper/live (enforcement is Phase 5; Phase 4 only marks `DEFERRED_TO_RISK`).
- **Fail closed:** uncertain data/connection/account/risk → NO_TRADE, no new orders.
- **Tech stack:** Python 3.13 (`requires-python = "==3.13.*"` [VERIFIED: pyproject.toml:5]), pytest + asyncio auto mode, Ruff + mypy strict on `src/`, Decimal/tick arithmetic for exchange-sensitive values.
- **GSD workflow:** implementation must run through GSD commands; no direct repo edits outside a workflow.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Feature computation (EMA/ATR/swing/zones) | Pure core (`src/core/`) | — | Deterministic math on closed candles; no I/O, no framework types |
| Setup detection (regime + trigger + confirmation) | Pure core (`src/core/`) | — | Pure function of snapshot + params; must run identically in backtest/paper/live |
| Trade-plan construction (entry/SL/TP/RR/hash) | Pure core (`src/core/`) | — | Same-input-same-plan; approval-bound hashes originate here |
| Enum promotion (direction/setup_type/timeframe/...) | Domain (`src/domain/enums.py`) | — | GLOSSARY-consistent vocabulary owned by the domain layer, consumed by core |
| Candle sourcing (Parquet → closed sequences) | Adapter edge | `src/data/` precedent | Core never touches storage; adapter converts rows to frozen candle inputs |
| Sizing/quantization enforcement | Phase 5 (risk) | — | Explicitly deferred; core emits estimates only |
| Backtest/intrabar simulation | Phase 6 | — | Consumes core + fixtures; never implemented inside core |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`decimal`, `datetime`, `hashlib`, `json`, `dataclasses`, `enum`) | 3.13 (`requires-python = "==3.13.*"` [VERIFIED: pyproject.toml:5]) | Entire `src/core/` implementation | D-10 purity: zero third-party imports; `Decimal` + canonical JSON + `str, Enum` mixin are the established Phase-3 precedents |
| In-repo `src/domain/` contracts | frozen Phase-3 | Signal/TradePlan/ids/canonical/registry/enums | Reuse verbatim — planner wires, never re-derives (see verified contracts below) |

No new third-party packages are installed in Phase 4. `PYTHONDONTWRITE` nothing; `uv add` nothing.

### Verified in-repo contracts (read this session — planner must conform)

**Signal shape** [VERIFIED: src/domain/signal.py:46-59] — fields verbatim:
`"signal_id, strategy_id, strategy_version, parameter_set_id, parameter_set_hash, symbol, direction, setup_type, source_timeframe, source_candle_close_utc, detected_at_utc, status, expires_at_utc, invalidated_at_utc"` with `direction`/`setup_type`/`source_timeframe` as validated non-empty strings pending D-06 enum promotion, and all datetimes UTC-aware (`_require_utc_aware`, lines 74-78).

**TradePlan shape** [VERIFIED: src/domain/trade_plan.py:59-78] — fields verbatim:
`"trade_plan_id, signal_id, trade_plan_version, entry_model, entry_min_price, entry_max_price, stop_loss_price, take_profit_json, invalidation_rule_json, expiry_utc, expected_rr_json, risk_rate, risk_budget, suggested_quantity, quantity_before_rounding, quantity_after_rounding, quantization_decision, plan_hash, status, created_at_utc"`; money/qty/price fields `Decimal`-only (lines 92-101), JSON-carrying fields stored as strings per DATA_MODEL §5.

**SignalId inputs** [VERIFIED: src/domain/ids.py:19-28] — kwargs verbatim:
`"strategy_id, strategy_version, parameter_set_id, symbol, source_timeframe, source_candle_close_utc, setup_fingerprint"`. Child plan IDs derive via `derive_child_id(parent_signal_id, discriminator)` with discriminator `"trade_plan:v1"` [VERIFIED: src/domain/trade_plan.py:9-10].

**Canonical hash profile** [VERIFIED: src/domain/canonical.py:71-84] — verbatim:
`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` UTF-8 → SHA256 hex; `Decimal` → `str()` preserving trailing precision (`"1.50" ≠ "1.5"`, line 49); `float` and `set`/`frozenset` raise loudly (lines 58-66). Plan hash (D-08) MUST reuse `sha256_hex`, never a second ad-hoc hasher.

**Registry whitelist** [VERIFIED: src/domain/registry.py:60-72] — values verbatim:
`"swing_lookback", "zone_tolerance_atr", "breakout_confirmation_bars", "entry_buffer_atr", "sl_buffer_atr", "minimum_rr", "signal_expiry_hours", "risk_rate", "minimum_risk_utilization_after_rounding"`. Type split [VERIFIED: src/domain/registry.py:210-217]: int keys verbatim `"swing_lookback", "breakout_confirmation_bars", "signal_expiry_hours"`; all others Decimal-or-int. New family keys (see below) extend this set via reviewed change + type-class assignment.

**Tracer parameter values** [VERIFIED: params/trend-pullback/baseline-v1.toml:20-28] — verbatim:
`swing_lookback = 20`, `zone_tolerance_atr = 0.5`, `breakout_confirmation_bars = 3`, `entry_buffer_atr = 0.1`, `sl_buffer_atr = 0.2`, `minimum_rr = 2.0` (normalizes to int `2`, still valid per lines 206-208), `signal_expiry_hours = 4`, `risk_rate = 0.005`, `minimum_risk_utilization_after_rounding = 0.6`; identity `strategy_id = "trend-pullback"`, `strategy_version = "v1.0.0"` (lines 16-17).

**Test/tooling pins** [VERIFIED: pyproject.toml:46-52,75-82]: `asyncio_mode = "auto"`, `testpaths = ["tests"]`; mypy `strict = true`, `files = ["src"]`. No-float AST guard scans the file list at [VERIFIED: tests/test_domain_no_float.py:17-31]; Phase 4 extends that list with `src/core/*` (guard logic itself is reusable verbatim, lines 34-65).

**Canonical vocabularies** [VERIFIED: src/domain/enums.py:16-143]: `SignalStatus` values verbatim `"DETECTED", "NOTIFIED", "VIEWED", "APPROVED", "SKIPPED_USER", "SKIPPED_BUSY", "EXPIRED", "INVALIDATED"`; `TradePlanStatus` verbatim `"READY", "APPROVAL_PENDING", "APPROVED", "EXPIRED", "INVALIDATED", "SUPERSEDED"`; `RejectionReason` includes `"NO_TRADE_REGIME", "RR_TOO_LOW", ..., "DATA_STALE"` (full list lines 130-143). GLOSSARY regime terms verbatim `"BULLISH", "BEARISH", "NEUTRAL", "NO_TRADE"` [VERIFIED: docs/GLOSSARY.md:26].

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` + `pytest-asyncio` | `>=9`, `>=1.4` (dev deps [VERIFIED: pyproject.toml:34-40]) | Golden fixtures + determinism suites | All Phase-4 verification; fixtures under `tests/fixtures/phase4/` mirroring `tests/fixtures/phase3/` layout |
| `ruff` / `mypy` | dev deps, `line-length = 100`, strict | Lint + type gate on `src/core/` | Same gates as Phase 3; extend no-float guard file list |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib-only core | NumPy/Polars inside `src/core/` | Rejected by D-10: framework math cannot be reproduced byte-identically by the live path and breaks the no-float AST story; Polars stays at adapter/research edges per ENGINEERING_PRINCIPLES ("Do not put strategy semantics inside pandas/Polars expressions") [VERIFIED: docs/01_ENGINEERING_PRINCIPLES.md:97-100] |
| Per-feature validity flags | Whole-bar silent NaN | Rejected by D-03: NaN propagation is exactly how warm-up bugs become phantom signals; explicit `valid/reason_code` fails closed |
| `Decimal` EMA/ATR | `float` indicators, quantize at output | Rejected: binary rounding at different series lengths changes hashed fingerprints; Decimal end-to-end preserves prefix-invariance |

**Installation:**
```bash
# Nothing to install — src/core/ is stdlib-only (D-10).
```

## Package Legitimacy Audit

Phase 4 installs zero external packages (`src/core/` is stdlib + in-repo `src/domain` only, per D-10). No registry verification required; no `uv add` commands may appear in plans.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| *(none — stdlib only)* | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
Parquet rows (1H + 4H closed candles)
        │  adapter edge: validate OHLC/volume/decimals,
        │  reject duplicates/regressions/OHLC-violations (D-04)
        ▼
┌────────────────── FEATURE ENGINE (src/core/features.py) ──────────────────┐
│ closed-candle sequences only; NEVER resample/forward-fill/read unclosed   │
│  closes ──▶ EMA(20/50/200) + ATR(14)  │  4H context computed independently │
│  highs/lows ──▶ swing H/L (lookback) ──▶ zones (tolerance_atr half-width)  │
│  every output: (value, valid: bool, reason_code) + features_valid summary │
└───────────────────────────────────────────────────────────────────────────┘
        │ FeatureFrame (frozen dataclass, Decimal values)
        ▼
┌────────────── STRATEGY (src/core/strategy.py: evaluate(...)) ─────────────┐
│ pure: (snapshot, account_state, strategy_version, parameter_set)           │
│  regime gate (4H) ──▶ setup gate (1H) ──▶ confirmation ──▶ RR pre-check   │
│  any required-feature-invalid ──▶ NO_TRADE + reason code (fail closed)     │
│  SETUP ──▶ Signal via ids.make_signal_id, detected_at = source close      │
└───────────────────────────────────────────────────────────────────────────┘
        │ Signal (NO_TRADE | SETUP)
        ▼
┌────────────── PLANNER (src/core/planner.py: plan(setup)) ─────────────────┐
│ entry zone ± entry_buffer_atr │ SL = structure ∓ sl_buffer_atr            │
│ TP1 @ minimum_rr, TP2 extension │ RR < minimum_rr ──▶ NO_TRADE (noMN)     │
│ invalidation JSON │ expiry = close + signal_expiry_hours                  │
│ plan_hash = sha256_hex(canonical JSON) │ estimates + DEFERRED_TO_RISK     │
└───────────────────────────────────────────────────────────────────────────┘
        │ TradePlan ──▶ golden fixtures (tests/fixtures/phase4/)
        │              (Phase 5 risk, Phase 6 backtest, Phase 8 approval)
```

### Recommended Project Structure
```text
src/
├── core/                # NEW — dependency-free pure core (D-10)
│   ├── __init__.py      # re-exports only, no logic
│   ├── types.py         # frozen Candle, FeatureFrame, FeatureOutput(valid/reason_code), SetupResult/NO_TRADE
│   ├── features.py      # EMA/ATR/swing/zone math, stdlib+Decimal only
│   ├── strategy.py      # evaluate() per family (tracer first), pure function
│   ├── planner.py       # SETUP -> TradePlan, ATR buffers, RR gate, plan_hash
│   └── enums.py         # re-export domain enums OR family-local reason codes (planner discretion)
├── domain/              # EXTEND — D-06 enum promotions in enums.py
└── adapters/            # EXTEND — Parquet-row -> Candle edge (if not already present)
tests/
├── fixtures/phase4/     # NEW — candles.csv + parameters.json + expected_{features,signals,plans}.json
├── test_core_features.py, test_core_strategy_*.py, test_core_planner.py  # NEW
└── test_domain_no_float.py  # EXTEND SCANNED_FILES with src/core/*
```

### Pattern 1: Per-feature validity flags with fail-closed strategy gate
**What:** Every feature returns `(value: Decimal | None, valid: bool, reason_code: str)`; a `features_valid` whole-bar summary ANDs required-feature validity. Strategy returns NO_TRADE with the first failing reason code instead of propagating partial values. [ASSUMED — recommended default from CONTEXT D-03; no upstream library, it is project-invented discipline]
**When to use:** All Phase-4 feature/strategy code, no exceptions.
**Example:** see §Code Examples (FeatureOutput sketch).

### Pattern 2: Tracer-first with shared harness
**What:** `trend-pullback/baseline-v1` end-to-end green first; `breakout-retest` and `range-mr` reuse the same fixture loader, determinism suites, and planner — only the `evaluate()` branch and new registry keys differ. Mirrors the family sheets' Stage A/B/C baselines as mandatory reference rows (never removed from the matrix). [CITED: docs/research/families/trend-pullback.md:56-66]
**When to use:** Plan slicing — tracer slice must stay first (D-05).

### Pattern 3: Canonical-hash reuse for every identity
**What:** SignalId via `make_signal_id`, plan IDs via `derive_child_id(..., "trade_plan:v1")`, parameter hashes via registry loader, plan_hash via `sha256_hex` over canonical JSON — one hasher, one profile, everywhere. [VERIFIED: src/domain/canonical.py:71-84]
**When to use:** Any new ID/hash introduced in Phase 4 (setup_fingerprint construction, plan_hash payload).

### Anti-Patterns to Avoid
- **Float anywhere in core:** a single `float(` literal or `Decimal(0.5)` (float-arg constructor) breaks byte-equivalence across series lengths; the AST guard flags literals AND `Decimal(float)` shapes [VERIFIED: tests/test_domain_no_float.py:47-64].
- **SMA/EMA/ATR off-by-one seeding:** emitting EMA at input `period-1` instead of `period`, or ATR at the wrong bar, shifts every warm-up gate; pin first-emission index in boundary tests (see Pitfall 1).
- **Interpolating 4H into 1H:** resampling or forward-filling across timeframes is lookahead by construction; keep sequences separate (D-02).
- **Redrawing ranges/zones post-break:** Family C binding rule is invalidation-not-redraw [CITED: docs/research/families/range-mr.md:44-49]; Family B retest countdown starts at breakout-bar *close* [CITED: docs/research/families/breakout-retest.md:128-132].
- **Declaring a winner:** any comparative "best/preferred/optimal" language without backtest+OOS evidence violates D012 (all three family sheets carry the TBD footer).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SHA256 canonical JSON | Custom digest/serializer | `src/domain/canonical.py::sha256_hex` | One profile (sorted keys, compact separators, Decimal→str); a second hasher risks divergent fingerprints between SignalId and plan_hash |
| Signal/plan IDs | UUIDs, counters, timestamps | `ids.make_signal_id` / `derive_child_id` | Content-hash IDs give restart-safe idempotency; wall-clock IDs break prefix-invariance |
| Parameter loading/validation | Custom TOML reader | `registry.load_parameter_set` | Fail-closed whitelist, ASCII, type, and hash checks already reviewed; ambient-key smuggling detection included |
| UTC validation | Ad-hoc tz checks | domain `_require_utc_aware` pattern | Naive-vs-aware and offset bugs become construction-time errors |
| Time-series math (Polars/NumPy) inside core | Vectorized indicator libs | Hand-written Decimal recurrences (cited formulas below) | V1 series are short (hundreds of closed candles); D-10 purity + determinism outweigh vectorization; escalate only on a profiled bottleneck per project policy |
| Retry/logging infra | Custom logger | Existing `structlog`/stdlib logging convention | Decision lineage must match the project-wide audit-trail schema |

**Key insight:** Phase 4's value is *identical semantics across backtest/paper/live*, which only holds if core math is stdlib-Decimal and every identity flows through the single canonical hasher. Any framework shortcut taken here compounds into Phase 6 parity bugs.

## Common Pitfalls

### Pitfall 1: EMA α vs Wilder α confusion
**What goes wrong:** ATR(14) implemented as EMA-of-TR with `α=2/15≈0.1333` instead of Wilder `α=1/14≈0.0714` (or vice versa) — every zone width, entry buffer, and SL shifts silently.
**Why it happens:** Both are "exponential smoothing with period 14" in casual language; they differ in the constant.
**How to avoid:** EMA uses `α = 2/(n+1)` SMA-seeded (TA-Lib convention) [CITED: docs.wickra.org/Indicators/Indicator-Ema; corroborated by TTR `MovingAverages.R` — "wilder=FALSE uses 2/(n+1), wilder=TRUE uses 1/n", github.com/joshuaulrich/TTR]; ATR uses Wilder `α = 1/n` seeded by SMA of first `n` true ranges, first emission at the n-th candle [CITED: docs.wickra.org/Indicators/Indicator-Atr; corroborated by polars-ta `atr.rs` — "ATR = RMA(TR, length)"]. Boundary fixtures must pin first-emission index AND a hand-computed value for each.
**Warning signs:** Zone widths differ from a reference implementation (TA-Lib/TTR) at identical inputs; backtest-vs-manual mismatch on the same candles.

### Pitfall 2: Decimal context precision leaking into hashed values
**What goes wrong:** `Decimal(a) / Decimal(b)` rounds to context `prec=28` (`ROUND_HALF_EVEN` default) [CITED: docs.python.org/3/library/decimal.html]; two runs with different ambient context (or mutated global `getcontext().prec`) produce different EMA/RR digits → different fingerprints/hashes.
**Why it happens:** `getcontext()` is thread-global mutable state; any library mutating it changes core math silently.
**How to avoid:** Never touch the global context in core; wrap divisions in `localcontext()` with explicit `prec` where needed, or prefer integer-ratio forms (`(n-1)*prev + x) / n` under a pinned local context); construct all Decimals from strings (`Decimal("0.5")`, never `Decimal(0.5)`) — the AST guard enforces this [VERIFIED: tests/test_domain_no_float.py:51-58]. Golden fixtures with byte-exact expected values catch drift.
**Warning signs:** Full-run digest differs between local and CI runs; `ROUND_HALF_EVEN` vs `ROUND_HALF_UP` disagreement on `.5` cases.

### Pitfall 3: Lookahead via right-side swing confirmation
**What goes wrong:** Swing high defined as "highest high in [t-N, t+N]" requires N *future* bars; evaluating setup at bar t using a swing confirmed at t+N is future leakage unless the decision timestamp is the confirmation bar's close.
**Why it happens:** Family sheets define pivots with left/right lookback [CITED: docs/research/families/trend-pullback.md:114-119] — "A swing is confirmed at the close of the bar at t+N. Decision-making uses confirmed swings only."
**How to avoid:** Timestamp every setup at the *confirmation* bar close; no-lookahead suite (prefix + appended-tail invariance per TESTING_STRATEGY §3 [VERIFIED: docs/testing/TESTING_STRATEGY.md:39-50]) must pass with real family expectations, not placeholders.
**Warning signs:** Signals whose `source_candle_close_utc` precedes the bars that define their own swing/zone.

### Pitfall 4: Gap-spanning features silently bridging missing candles
**What goes wrong:** A missing-candle gap inside an EMA/ATR recursion is treated as a zero-change step, damping volatility estimates and shifting zones.
**Why it happens:** Recursion `(prev*(n-1)+x)/n` has no notion of time distance; feeding non-contiguous closes fabricates continuity.
**How to avoid:** D-04: adapter emits explicit gaps (Phase-2 flag-never-fabricate precedent); any feature whose window spans a gap reports `valid=False, reason_code="GAP_IN_SOURCE"` (or a documented additive degrade rule); strategy NO_TRADEs. Gap fixtures (deleted middle rows) are mandatory boundary cases.
**Warning signs:** Features valid across known outage windows; backtest/paper divergence after reconnects.

### Pitfall 5: Enum-promotion string drift
**What goes wrong:** New `Direction`/`SetupType`/`SourceTimeframe` enum `.value`s differ by even one character from the strings already stored in Phase-3 fixtures/rows, breaking fixture equality and (later) stored-row restores.
**Why it happens:** D-06 promotion happens after strings are already in fixtures.
**How to avoid:** Enum values MUST copy the exact Phase-3 strings (`"LONG"`, `"SHORT"`, family setup names, `"1h"`/`"4h"`-style timeframe spellings as used in `phase3_candles.csv`); unknown values stay load-time errors (`Enum(value)` raising `ValueError` is the reviewed Phase-3 pattern [VERIFIED: STATE.md:89]); extend the ORM-translation pattern (`.value` store / `Enum(value)` restore).
**Warning signs:** Fixture diffs showing only case/separator changes; `ValueError` on previously-valid stored rows.

### Pitfall 6: TP2/RR-gate ambiguity becoming a silent downgrade
**What goes wrong:** When TP2 extension math yields RR below `minimum_rr`, an implementation "helpfully" emits a TP1-only plan instead of NO_TRADE.
**Why it happens:** D-08's "never a downgraded plan" rule is easy to soften at the code face.
**How to avoid:** RR check is a hard gate returning `NO_TRADE` + `RR_TOO_LOW` (canonical `RejectionReason.RR_TOO_LOW` [VERIFIED: src/domain/enums.py:130-131]); boundary fixtures pin exact-equality/just-below/just-above `minimum_rr` per TESTING_STRATEGY §5 [VERIFIED: docs/testing/TESTING_STRATEGY.md:69-78].
**Warning signs:** Plans with realized RR < registry `minimum_rr` in any fixture.

## Code Examples

Verified patterns from official/secondary sources and in-repo precedent:

### EMA (TA-Lib convention, Decimal adaptation)
```python
# Source: docs.wickra.org/Indicators/Indicator-Ema (alpha + SMA-seed convention),
# corroborated by TTR MovingAverages.R (github.com/joshuaulrich/TTR).
# Formula (float original, port to Decimal with str-constructed constants):
#   alpha = 2 / (period + 1)
#   seed  = SMA(first `period` closes)            # first emission at input `period`
#   EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
from decimal import Decimal, localcontext

def ema_update(prior: Decimal, price: Decimal, alpha: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28  # pinned; never inherit ambient getcontext().prec [CITED: docs.python.org/3/library/decimal.html]
        return alpha * price + (Decimal(1) - alpha) * prior
```
Warm-up: `valid=True` first at index `period-1` (0-based) of the closed sequence; before that `WARMUP_INSUFFICIENT` [ASSUMED index convention — planner pins in fixtures; the SMA-seed-then-recurse shape itself is CITED].

### ATR (Wilder convention, Decimal adaptation)
```python
# Source: docs.wickra.org/Indicators/Indicator-Atr + polars-ta atr.rs
# (github.com — "ATR = RMA(TR, length), alpha = 1/length").
#   TR_t  = max(H-L, |H - C_prev|, |L - C_prev|); TR_1 = H_1 - L_1 (no prev close)
#   seed  = SMA(first `period` TRs)               # first emission at n-th candle
#   ATR_t = ((period - 1) * ATR_{t-1} + TR_t) / period
def true_range(high: Decimal, low: Decimal, prev_close: Decimal | None) -> Decimal:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))
```

### Swing + zone (project-defined, no upstream — pure rule transcription)
```python
# Source: family sheets (no upstream library; semantics below are CITED to sheets).
# Swing high at t: high[t] == max(high[t-N .. t+N]) with confirmation at close(t+N)
#   [CITED: docs/research/families/trend-pullback.md:114-119].
# Zone: cluster of >= zone_min_touches swings; half-width = zone_tolerance_atr * ATR
#   [CITED: trend-pullback.md §2.2 + §6 parameter table].
# Boundary merge/collide/separate rule [CITED: trend-pullback.md:124-130]:
#   merge if midpoint-distance < combined half-widths (bounds = union);
#   collide at exactly one price level -> single zone for entry, two for invalidation;
#   positive gap -> independent zones.
# Range-break invalidation (Family C): 1H close beyond edge by > range_break_buffer_atr
#   -> invalidate, NEVER redraw [CITED: docs/research/families/range-mr.md:44-49].
```

### Planner math (ATR buffers + RR gate + expiry + hash)
```python
# Field contract [VERIFIED: src/domain/trade_plan.py:59-78]; whitelist keys
# [VERIFIED: src/domain/registry.py:60-72]; tracer values
# [VERIFIED: params/trend-pullback/baseline-v1.toml:20-28].
# LONG (mirror for SHORT):
#   entry_max   = zone_upper + entry_buffer_atr * ATR      # entry_buffer_atr = 0.1
#   entry_min   = zone_lower - entry_buffer_atr * ATR
#   stop        = swing_low - sl_buffer_atr * ATR          # sl_buffer_atr = 0.2
#   risk        = entry_ref - stop  (entry_ref documented per plan: zone mid or worst-fill edge)
#   TP1         = entry_ref + minimum_rr * risk            # minimum_rr = 2.0
#   RR_TP1      = (TP1 - entry_ref) / risk  -> must be >= minimum_rr else NO_TRADE(RR_TOO_LOW)
#   expiry_utc  = source_candle_close_utc + timedelta(hours=signal_expiry_hours)  # 4
#   plan_hash   = sha256_hex({signal_id, entry_min, entry_max, stop, tps, invalidation, expiry})
#   quantization estimates: suggested_quantity etc. as Decimal + quantization_decision =
#     "DEFERRED_TO_RISK" (D-09; Phase 5 owns stepSize math)
```

### NO_TRADE / SETUP envelope (project pattern)
```python
# NO_TRADE reason codes reuse canonical RejectionReason values where applicable
# ("NO_TRADE_REGIME", "RR_TOO_LOW", "DATA_STALE" [VERIFIED: src/domain/enums.py:130-143])
# plus additive warm-up/gap codes ("WARMUP_INSUFFICIENT", "GAP_IN_SOURCE" per D-03/D-04).
# detected_at_utc = source_candle_close_utc (candle-close timing, D-07).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `float` indicators, quantize at output | `Decimal` end-to-end in core | Phase 3 D-12, extended Phase 4 D-10 | Byte-equivalent decisions; AST guard enforces |
| Placeholder determinism suites (per-candle hash mapping) | Real family expectations in no-lookahead/prefix/timing/boundary suites | Phase 4 (this phase) | Suites become genuine acceptance evidence for Phase 6 |
| String status/setup fields | GLOSSARY-consistent Enums (`str, Enum` mixin, values verbatim) | Phase 3 D-10 precedent, Phase 4 D-06 | Type-checked vocabulary; unknown values fail at load |
| Single-timeframe evaluation | 1H setup + independent 4H context, separate closed sequences | Phase 4 D-02 | No interpolation lookahead; 1m reserved for Phase 6 intrabar |
| Ad-hoc plan dicts | Frozen `TradePlan` + canonical `plan_hash` | Phase 3 shape, Phase 4 behavior | Approval binding in Phase 8 rests on this hash |

**Deprecated/outdated:**
- Legacy `binance-connector` / `binance-futures-connector` (archived 2026-04-30): never touch core; core has no exchange imports at all.
- VectorBT/pandas-based strategy semantics: exploratory only; canonical semantics live in `src/core/` per ENGINEERING_PRINCIPLES.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | EMA warm-up = first emission at 0-based index `period-1` via SMA seed; ATR first emission at n-th candle | Code Examples, Pitfalls | Off-by-one warm-up gates; mitigated by boundary fixtures pinning first-emission index |
| A2 | `Decimal` division under pinned `localcontext(prec=28)` is sufficient precision for EMA/ATR/RR chains (no long-division drift vs exchange ticks) | Pitfalls | Sub-tick drift in hashed values; mitigated by byte-exact fixtures across CI/local |
| A3 | `quantization_decision = "DEFERRED_TO_RISK"` string (or Enum equivalent) — exact token chosen by planner | Planner contract | Phase 5 must match the token; mitigated by D-06 enum promotion covering it |
| A4 | TP2 extension rule (beyond TP1 at `minimum_rr`) — planner discretion per CONTEXT | Code Examples | TP2 semantics enter fixtures/backtest parity; costly to change later — planner should pick the simplest rule (documented constant multiple or opposite-structure) and fixture it |
| A5 | Family B/C new registry keys (`retest_window_bars`, `retest_depth_atr`, `breakout_volume_threshold`, `zone_min_touches`, `zone_aging_bars`, `range_break_buffer_atr`, `regime_filter_lookback`, variant enums) — names/discretion per planner | Standard Stack | Registry whitelist extension is one-way; planner must review names once, since parameter hashes are permanent |
| A6 | Wickra/TTR/polars-ta formula pages correctly state TA-Lib/Wilder conventions (secondary, non-official-TA-Lib sources) | Code Examples, Pitfalls | Wrong smoothing constant; mitigated by triple-source agreement + hand-computed fixture values |

## Open Questions

1. **TP2 extension rule details**
   - What we know: TP1 at `minimum_rr`; TP2 is an "extension" (D-08); Family C has explicit T-mid vs T-opposite modes [CITED: range-mr.md:66-78].
   - What's unclear: Exact TP2 formula for trend-pullback and breakout-retest tracers.
   - Recommendation: Planner picks one simple documented rule (e.g., TP2 = entry + k×risk with registered k, or next-structure with fallback), fixtures it, and notes it as costly-to-change.

2. **Setup-fingerprint composition**
   - What we know: `make_signal_id` takes an opaque `setup_fingerprint` string [VERIFIED: src/domain/ids.py:19-28]; it must bind regime + setup + confirmation inputs.
   - What's unclear: Exact fingerprint field list per family (must include parameter-influencing values so distinct rules never collide).
   - Recommendation: Fingerprint = canonical JSON of (family id, variant codes, regime verdict + confirming bar closes, trigger bar close, zone bounds, ATR value); fixture the byte-exact strings.

3. **`source_timeframe` value spelling for multi-timeframe decisions**
   - What we know: 1H setup + 4H context arrive as separate sequences (D-02); Signal carries a single `source_timeframe` string.
   - What's unclear: Whether the signal's timeframe is the setup TF (`"1h"`) with 4H context recorded in the fingerprint, or a composite.
   - Recommendation: `source_timeframe` = setup timeframe; 4H context bar closes folded into `setup_fingerprint`. Planner locks spelling against `phase3_candles.csv` conventions.

## Environment Availability

Phase 4 is pure stdlib + in-repo code with no external services, tools, or packages. Per protocol this section records the (null) dependency surface:

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python interpreter | `src/core/` + pytest | ✓ (pinned) | 3.13 (`requires-python = "==3.13.*"` [VERIFIED: pyproject.toml:5]) | — |
| pytest + plugins | Validation Architecture | ✓ (dev deps) | `pytest>=9`, `pytest-asyncio>=1.4` [VERIFIED: pyproject.toml:34-40] | — |
| Parquet/PostgreSQL/Binance | Nothing in Phase 4 | N/A | — | Fixture CSVs stand in for Parquet rows |

**Missing dependencies with no fallback:** none — nothing blocks execution.
**Missing dependencies with fallback:** none.

## Validation Architecture

| Property | Value |
|----------|-------|
| Framework | pytest >= 9 (`pytest>=9` [VERIFIED: pyproject.toml:35]), `asyncio_mode = "auto"` [VERIFIED: pyproject.toml:47] |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/ -q -x` |
| Full suite command | `uv run pytest tests/ -q` (+ `ruff check src tests` + `mypy` per gates) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRAT-01 | EMA/ATR/swing/zone values + warm-up invalid + gap invalid, closed-candles only | unit (golden fixtures) | `uv run pytest tests/test_core_features.py -q` | ❌ Wave 0 |
| STRAT-02 | Pure evaluate() → NO_TRADE/SETUP + deterministic SignalId; no-lookahead + prefix-invariance + close-timing over real expectations | unit + determinism suites | `uv run pytest tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_core_strategy_trend_pullback.py -q` | ❌ Wave 0 (suites exist as placeholders, need real expectations) |
| STRAT-03 | Entry/SL/TP/invalidation/expiry/RR/plan_hash incl. RR-gate → NO_TRADE + DEFERRED_TO_RISK estimates | unit (golden fixtures) + boundary | `uv run pytest tests/test_core_planner.py -q` | ❌ Wave 0 |
| D-06 | Enum promotion: values verbatim, unknown → load-time error | unit | extend existing enum/translation tests | ❌ Wave 0 |
| D-10 | No-float AST guard over `src/core/*` + mypy strict | static | `SCANNED_FILES` extension + `mypy` | ❌ Wave 0 (one-line list extension) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -q -x` (full file scope is seconds-scale; suite is fixture-driven, no network/DB)
- **Per wave merge:** full suite + `ruff check` + `ruff format --check` + `mypy`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/fixtures/phase4/` — candles.csv (1H + 4H closed, incl. gap injection + warm-up-short prefixes) + parameters.json + expected_{features,signals,plans}.json (byte-exact, hand-computed EMA/ATR seed values)
- [ ] `tests/test_core_features.py`, `tests/test_core_strategy_*.py` (tracer + 2 slices), `tests/test_core_planner.py` — real expectations replacing Phase-3 placeholder mappings
- [ ] `tests/test_domain_no_float.py::SCANNED_FILES` — append `src/core/*` modules
- [ ] `tests/conftest.py` — `phase4_*` fixtures mirroring the `phase3_*` loader pattern [VERIFIED: tests/conftest.py:70-102]

## Security Domain

`security_enforcement: true`, ASVS Level 1 ([VERIFIED: .planning/config.json:57-59]). Phase 4 is a pure offline core: no network, no secrets, no sessions, no crypto. Applicable surface is input validation + safe arithmetic.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | No identities in core; approval auth is Phase 8 |
| V3 Session Management | no | No sessions; stateless pure functions |
| V4 Access Control | no | No principals/resources in core |
| V5 Input Validation | **yes** | Adapter validates candle fields (OHLC ordering, monotonic timestamps, Decimal-from-string); registry loader whitelist + type gates reused; unknown enum values raise at load |
| V6 Cryptography | partial | No new crypto; reuse `sha256_hex` for plan_hash — never hand-roll digest code |
| V14 Configuration | **yes** | Strategy-semantic keys live ONLY in registry; `check_strategy_key_outside_registry` rejects ambient smuggling [VERIFIED: src/domain/registry.py:404-423] |

### Known Threat Patterns for stdlib-only core

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/gapped candle input → phantom signal | Tampering | Fail-closed quality rejects + `GAP_IN_SOURCE` invalid (D-04); quality-reject-before-compute ordering |
| Ambient-config parameter smuggling | Tampering / Elevation | `check_strategy_key_outside_registry` gate; registry is the sole strategy-semantic source |
| Float-injection via fixture/adapter Decimals | Tampering | `Decimal(str)` construction only; AST no-float guard extended to `src/core/` |
| Context-precision manipulation (`getcontext().prec`) | Tampering | Pinned `localcontext()` in core; global context never mutated |

## Sources

### Primary (HIGH confidence)
- In-repo contracts read this session: `src/domain/signal.py`, `trade_plan.py`, `ids.py`, `canonical.py`, `registry.py`, `enums.py`; `params/trend-pullback/baseline-v1.toml`; `tests/conftest.py`, `test_domain_no_float.py`, `test_prefix_invariance.py`; `pyproject.toml`; `.planning/config.json`
- Canonical docs read this session: `docs/GLOSSARY.md`, `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/testing/TESTING_STRATEGY.md`, `docs/data/DATA_MODEL.md` (§§2.3–2.4), `docs/trading/SIGNAL_AND_ALERTS.md`, `docs/configuration/CONFIGURATION.md`, `docs/strategy/TRADING_STRATEGY_SPEC.md`, family sheets `trend-pullback.md` / `breakout-retest.md` / `range-mr.md`, `.planning/phases/04-*/04-CONTEXT.md`

### Secondary (MEDIUM confidence)
- [CITED: docs.wickra.org/Indicators/Indicator-Ema] — EMA `α=2/(n+1)`, SMA seed, first emission at input `period`
- [CITED: docs.wickra.org/Indicators/Indicator-Atr] — Wilder `α=1/n`, SMA-of-TR seed, first emission at n-th candle
- [CITED: github.com/joshuaulrich/TTR (R/MovingAverages.R)] — corroborates EMA `2/(n+1)` vs Wilder `1/n` + SMA-seed convention
- [CITED: polars-ta `atr.rs` source docs] — corroborates ATR = RMA(TR, length)
- [CITED: docs.python.org/3/library/decimal.html] — context `prec=28`/`ROUND_HALF_EVEN` defaults, `localcontext()` isolation, `quantize()` semantics, string-construction requirement

### Tertiary (LOW confidence)
- None relied upon; all [ASSUMED] items are logged in §Assumptions Log for planner/user confirmation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; every contract verified by Read with line citations.
- Architecture: HIGH — CONTEXT D-01–D-10 lock the shape; family sheets lock per-family rules; only TP2/fingerprint/timeframe-spelling details are planner-discretion.
- Pitfalls: HIGH — top two pitfalls (α-confusion, Decimal context) verified against cited sources; remainder are direct transcriptions of locked decisions.

**Research date:** 2026-09-23
**Valid until:** ~30 days (stable domain: indicator math and in-repo contracts change slowly; re-verify only if Phase-3 contracts or registry whitelist change first)
