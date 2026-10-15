# 16-DEC-O-03b: values of the first research run's dataset manifest (plan 16-37, Task 2)

option: values
decided by: user
date: 2026-10-15
words:
ok theo khuyến nghị, sửa 1-4 và ghi O-03b

context (recorded for audit): the words above are the user's whole typed reply. They answer the assistant's check of the value block the user pasted into the session on 2026-10-15 (text reproduced below as pasted; its authorship before the paste is not recorded) and adopt the assistant's corrections 1 to 4. The pasted block is kept verbatim; the corrections are listed after it and the final values follow. This record decides the manifest VALUES only (plus the constraint file named in `16-DEC-O-03b-constraint.md`). It does not build or freeze a manifest, does not authorize any run, and does not read or consume the Holdout.

## Pasted by the user (verbatim, before corrections)
```
values
window_start_utc: 2024-10-03T00:00:00Z
window_end_utc: 2026-10-03T00:00:00Z

development: 2024-10-03T00:00:00Z .. 2025-07-22T00:00:00Z

validation: 2025-07-22T00:00:00Z .. 2026-05-10T00:00:00Z
validation_folds:
  - 2025-07-22T00:00:00Z .. 2025-10-03T00:00:00Z
  - 2025-10-03T00:00:00Z .. 2025-12-15T00:00:00Z
  - 2025-12-15T00:00:00Z .. 2026-02-26T00:00:00Z
  - 2026-02-26T00:00:00Z .. 2026-05-10T00:00:00Z

holdout: 2026-05-10T00:00:00Z .. 2026-10-03T00:00:00Z

universe: research-universe-v1
symbols: 12 symbol, giữ REEFUSDT
strategy_interval: 1h
context_interval: 4h

data_source: binance-usdm-public
data_source_version: local-data/raw Parquet snapshot; inventory_sha256=b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34; inventory verified 2026-10-03; partitions through 2026-10-02

excluded_periods: []

equity: 600
risk_rate: 0.005

constraint: baseline S0
constraint_file: docs/research/preregistration/research-run-1-constraints-baseline.json
constraint_sha256: 4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f

reef_terminal:
  symbol: REEFUSDT
  reason: DELISTED_CAPPED
  terminal_at_utc: 2025-01-22T09:00:00Z
  settlement_price_lower_bound: 0.000845
  settlement_price_upper_bound: 0.000887
  source_url: https://www.binance.com/en/support/announcement/detail/572715f2d96e47769ebbb967c2a6e445
```

## Corrections adopted by the user's reply (assistant's items 1 to 4)
1. `inventory verified 2026-10-03` becomes `inventory verified 2026-10-13`: the file listing was built on 2026-10-13 (`evidence/16-37-data-snapshot.md`, line 3); 2026-10-03 is the run date of the universe sufficiency report.
2. `symbols` is the explicit list of the 12 symbols of `research-universe-v1` (universe file `content_sha256` d6223620ade78290ca6b0a2eeeadd3430eb35316a42c78894afa2d62a82a1682).
3. The constraint file path is relative to the repository root; the runner reads it relative to the current working directory (`src/research/run.py:90`), so a run starts from the repository root. The path string is part of the manifest hash.
4. Dataset limitation: the dataset holds no open-interest series and the runner does not read open interest (D059 item 4); the dataset is not called full history.

## Final values (what the manifest build uses)
```
universe_id: research-universe-v1
symbols: 1000PEPEUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, DOGSUSDT, ETHUSDT, REEFUSDT, SOLUSDT, SUIUSDT, WIFUSDT, WLDUSDT, XRPUSDT
window_start_utc: 2024-10-03T00:00:00Z
window_end_utc: 2026-10-03T00:00:00Z
development_start_utc: 2024-10-03T00:00:00Z
development_end_utc: 2025-07-22T00:00:00Z
validation_start_utc: 2025-07-22T00:00:00Z
validation_end_utc: 2026-05-10T00:00:00Z
validation_folds: 4 x 73 days (2025-07-22, 2025-10-03, 2025-12-15, 2026-02-26, 2026-05-10 boundaries)
holdout_start_utc: 2026-05-10T00:00:00Z
holdout_end_utc: 2026-10-03T00:00:00Z
strategy_interval: 1h
context_interval: 4h
data_source: binance-usdm-public
data_source_version: local-data/raw Parquet snapshot; inventory_sha256=b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34; inventory verified 2026-10-13; partitions through 2026-10-02
excluded_periods: []
equity: 600
risk_rate: 0.005
constraint_source: docs/research/preregistration/research-run-1-constraints-baseline.json
constraint_sha256: 4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f
known_gaps: REEFUSDT, DELISTED_CAPPED, terminal_at_utc 2025-01-22T09:00:00Z, source_url https://www.binance.com/en/support/announcement/detail/572715f2d96e47769ebbb967c2a6e445
terminal_settlements: REEFUSDT, price_lower 0.000845, price_upper 0.000887 (the other fields come from the committed evidence under docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/, recomputed and checked by the runner)
```

## Checks the assistant made before this record (facts, not decisions)
- The five boundaries give 292, 73, 73, 73, 73 and 146 days (730 in total); every boundary is 00:00Z; the Validation block divides into four equal folds, which match `DatasetManifest.validation_folds()`.
- The universe file lists exactly the 12 symbols above, equal to the symbol set of the S0 constraint file.
- The REEF reason is in the closed vocabulary, the URL host is allowed, and the terminal lies inside Development (before `validation_start_utc`).
- `data_source` equals the string used by the test fixtures; the origin of the local data was not verified by the assistant. The Holdout bytes were not read.

## Not decided by this record
`dataset_id` and the manifest hash (computed by the build from the day files inside the window), the S1 manifest (same values except the constraint file, `fd86906a…`; its own freeze and words), the grid and authorization files, the freeze of the manifest (needs the user's own words), O-03 / plan 16-46, any run, any Holdout read, `holdout_consumed.json`, ExperimentRecord, push.
