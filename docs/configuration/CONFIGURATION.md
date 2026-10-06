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

### Runtime configuration of the Phase 13 data tools

These are command-line settings of the data tools (D049). They are runtime configuration, not strategy parameters: none is a registry key, none enters `parameter_set_hash`, and the exact data a run used is identified afterwards by the dataset identity (`data/DATA_MODEL.md` section 2.13) and the sufficiency report.

Collector, `python -m src.data.collector`:

| Setting | Default | Behavior |
| --- | --- | --- |
| `--collect-list` | `DEFAULT_COLLECT_LIST_PATH` in `src/data/collect_list.py`, that is `docs/research/universe/collect-list-v2.toml` relative to the working directory (the repository root locally, `/app` in the image, which ships `docs/research/universe`) | The symbols the OI and funding collector polls. The latest versioned list under `docs/research/universe` is the one in use; after the research-universe freeze a new list version is issued and the path is updated (D-24). |
| `--universe` | none | Explicit symbol override, validated against `^[A-Z0-9]+USDT$`. |
| `--cadence-seconds` | 300 | Poll cadence; the loop sleeps to the next grid boundary. |
| `--raw-root`, `--database-url` | `data/raw`, `DATABASE_URL_SYNC` or `DATABASE_URL` | Parquet raw store and watermark database. |
| `--once`, `--healthcheck` | off | One tick and exit; watermark-freshness probe. |

Refusal behavior: a missing, unreadable, malformed or empty collect list, or an invalid symbol in it, makes the collector exit 2 (the healthcheck exit 1) before any engine or adapter is built. There is no fallback to the five live symbols.

Collect-list proposer, `python -m src.data.collect_list propose --ticker-json P --exchange-info-json P --chosen-on YYYY-MM-DD [--top-n N] [--list-id ID] --out P`: deterministic, refuses to overwrite `--out`.

History backfill, `python -m src.data.backfill_cli`:

| Setting | Default | Behavior |
| --- | --- | --- |
| `--symbols` | the collect list union a FROZEN manifest | Explicit symbols replace the union (a FROZEN manifest still sets the 1h/4h start). |
| `--collect-list`, `--manifest` | the collect list above; `docs/research/universe/research-universe-v1.toml` | A missing or invalid manifest is a configuration error (exit 2). A DRAFT manifest contributes nothing; a FROZEN one adds its symbols and its `selection_date` becomes the 1h/4h start. |
| `--intervals`, `--datasets` | `1m 1h 4h`; `trade mark` | What to fetch. |
| `--depth-1m-months`, `--depth-htf-months` | 12, 24 | History depth before the run date (D-04). Extending 1m to 24 months is a user decision after the sufficiency report (D-21). |
| `--pace-seconds` | 0.25 | Pause between pages; at page size 1000 (weight 5) about 1,200 weight per minute, half of the IP budget. |
| `--raw-root`, `--cursor-root` | `data/raw`, `data/raw/_cursors` | Store root and per-dataset resume cursors (plus `_sources.json`, the REST or ARCHIVE provenance of archive-filled symbols). |
| `--report-out` | none (the table is always printed) | Writes the data-sufficiency report as canonical JSON. |
| `--funding`, `--no-funding` | funding on | Funding-history backfill per symbol over the 1h/4h range. |
| `--dry-run` | off | Reads exchangeInfo, prints every window, fetches and writes nothing. |
| `--database-url` | `DATABASE_URL_SYNC` or `DATABASE_URL` | Read once by the engine factory and never printed. |

Exit codes: 0 success, 1 a runtime failure (only exception type names are printed, never a URL), 2 a configuration error, 3 missing data (`NOT_BACKFILLED`, `GAP` or `UNAVAILABLE` in the sufficiency report). `python -m src.data.sufficiency validate <report>` checks a written report.

Point-in-time universe freeze, `python -m src.data.universe_freeze`:

| Command and setting | Default | Behavior |
| --- | --- | --- |
| `propose --run-date D --out P` | today (UTC); `docs/research/universe/research-universe-v1.freeze-report.json` | Ranks candidates by trailing 30-day quote volume at the dataset start (the run date minus two years) and writes the hashed report; exit 3 when fewer than 12 symbols are eligible (the report is still written). |
| `freeze --report P --approve HASH [--freeze] [--manifest P] [--witness P]` | dry run unless `--freeze` | Approval-hash rule: `--approve` must equal the `proposal_sha256` recomputed from the report; an edited report, a manifest that is not DRAFT, a witness that is already set or a proposal that fails manifest validation refuses with no file changed. With `--freeze` the manifest and the second witness are written atomically and the manifest is restored if the witness write fails. |

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
- The current sets are `baseline-v6` (three families), `baseline-no-trade-v4` and `baseline-simple-trend-v4` at `strategy_version` v5.0.0; the older sets (`baseline-v5`, `baseline-v4`, `baseline-no-trade-v3`, `baseline-simple-trend-v3` and earlier) stay unchanged and hash-locked.
- `exit_slippage_rate` joins `cost_model_hash` by presence, so v5 sets carry an eight-key cost identity and older sets keep their seven-key identity (D047).

Phase 15 geometry keys (D054):

| Key | Type | Unit | Constraint | Read by |
|-----|------|------|------------|---------|
| `pivot_left_bars` | integer | bars | 1 to 50; given together with `pivot_right_bars`, never alone; needs `geometry_version` | trend-pullback and range-mr only |
| `pivot_right_bars` | integer | bars | 1 to 50; given together with `pivot_left_bars`; `pivot_right_bars` + 1 must not exceed `swing_lookback`; needs `geometry_version` | trend-pullback and range-mr only |
| `geometry_version` | integer | none | closed set {1}; absent means the legacy behavior; in a trend-pullback or range-mr set it needs both pivot keys, and in a range-mr set also `tp_mode` | all three families |
| `tp_mode` | string | none | `T_MID` or `T_OPPOSITE`; needs `geometry_version` | range-mr only |
| `min_stop_atr` | Decimal | multiple of ATR | greater than 0 and at most 10 | any family (shared planner stop invariant) |

- Runtime configuration must not reuse these key names.
- A breakout-retest set takes no pivot keys; it reads `geometry_version` for the with-direction gate, the evaluated-bar anchoring and the narrow-zone stop.
- `geometry_version` is the switch for the corrected geometry: sets that omit it keep the legacy behavior byte for byte, and the older sets stay hash-locked.
- Values of these keys in a set are recorded with a basis in the set's in-file rationale table; a PLACEHOLDER basis keeps the set research-only and is not evidence.
