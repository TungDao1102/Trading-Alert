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
