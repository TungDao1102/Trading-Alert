# Configuration and Parameter Registry

## 1. Purpose

Every strategy parameter that can affect a signal or trade plan must be versioned and reproducible.

The source of truth is a **parameter set**, not a mutable environment file.

## 2. Parameter set identity

Each parameter set has:

```text
parameter_set_id
strategy_id
strategy_version
parameter_set_hash
schema_version
parameters_json
created_at_utc
created_by
status
```

`parameter_set_hash` is a deterministic hash of the canonical serialized parameter document.

## 3. Runtime configuration vs strategy parameters

Separate:

### Strategy parameters

Examples:

```text
swing_lookback
zone_tolerance_atr
breakout_confirmation_bars
entry_buffer_atr
sl_buffer_atr
minimum_rr
signal_expiry_hours
risk_rate
minimum_risk_utilization_after_rounding
```

These belong in the parameter registry and are part of backtest identity.

### Runtime configuration

Examples:

```text
Binance endpoint
Telegram bot token reference
DB connection reference
logging level
poll interval
feature flags
```

Runtime configuration may live in environment variables or secret/config stores, but must never silently modify strategy semantics.

Runtime configuration must not use the name `working_type` or any other registry key name: registry keys are strategy-semantic and are rejected outside the registry (D037).

## 4. Reproducibility contract

Every backtest, paper signal, alert, approval, and live order plan must be traceable to:

```text
strategyVersion
parameterSetId
parameterSetHash
```

A live order must never use an unregistered parameter set.

## 5. Immutable frozen sets

Once a parameter set is used for a published backtest or live-approved plan:

- do not mutate it;
- create a new parameter set;
- bump the strategy version when behavior changes materially.

## 6. Storage model

Recommended hybrid:

```text
source-controlled JSON/YAML
        ↓
validated loader
        ↓
canonical normalized JSON
        ↓
DB parameter registry
```

The DB record stores the exact normalized snapshot used by the run.

## 7. Experiment linkage

An experiment must record:

```text
experimentId
strategyVersion
parameterSetHash
dataSnapshotId
codeVersion
costModelHash
```

No backtest report is considered reproducible without these identifiers.

## 8. Parameter search rules

Automated sweeps are allowed only inside ranges declared by research.

The agent must not invent a search space after seeing the result distribution.

Results must be grouped by parameter region, not only by the single best point.

A narrow isolated optimum is a robustness warning; see `TRADING_STRATEGY_RESEARCH.md`.


## 9. Python configuration conventions

- `pyproject.toml` contains dependency/tool configuration, not secrets.
- Environment variables or an external secret store contain runtime secret references.
- Strategy parameter files use a canonical JSON/YAML representation before hashing.
- The loader must normalize numeric types and key ordering before computing `parameterSetHash`.
- Research notebooks must load parameter sets through the same library code used by the backtest runner.

## 10. Canonical cost and execution assumptions for versioned sets

- `fee_rate_entry` is modeled at the taker rate for canonical sets (D036).
- `partial_fill_fraction` is 1.0 for every canonical set; partial or missed fills are a separate sensitivity run (D038).
- `working_type` is an optional closed-set string key; the registry admits only `MARK_PRICE` (D037). `CONTRACT_PRICE` is rejected at load until the backtest simulator (Phase 14) and live placement (Phase 19) read the key; canonical sets use `MARK_PRICE`.
- Old sets are never edited; they are superseded by new versions (`baseline-v4`, `baseline-no-trade-v2`, `baseline-simple-trend-v2`; D036-D038).
- The point-in-time research universe manifest at `docs/research/universe/research-universe-v1.toml` is not a parameter set (D039).

Phase 12 cost keys (D046):

| Key | Type | Unit | Baseline | Constraint | Decision |
|-----|------|------|----------|------------|----------|
| `exit_slippage_rate` | Decimal | decimal fraction of price | 0.0003 | 0 to 0.01; separate from `expected_slippage`; applied to SL and EOD exits | D046 |
| `min_stop_distance_rate` | Decimal | fraction of the sizing entry price | 0.003 | open interval 0 to 1 | D046 |
| `max_cost_to_risk` | Decimal | ratio of round-trip modeled cost to risk per unit | 0.15 | greater than 0 and at most 1 | D046 |
| `commission_rate_ttl_seconds` | integer | seconds | 3600 | greater than 0 | D046 |

- Fee and slippage rates above 0.01 are rejected at load as unit errors (rates are decimal fractions, not basis points).
- Runtime configuration must not reuse these key names.
- The keys are optional in parameter sets that predate Phase 12 and required by the simulator and sizing; legacy sets are refused for sizing and simulation rather than defaulted.
- The current sets are `baseline-v5` (three families), `baseline-no-trade-v3` and `baseline-simple-trend-v3` at `strategy_version` v4.0.0; the older `baseline-v4` sets stay unchanged and hash-locked.
- `exit_slippage_rate` joins `cost_model_hash` by presence, so v5 sets carry an eight-key cost identity and older sets keep their seven-key identity (D047).
