# Phase 13: Research Data Foundation Fixes - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-30
**Phase:** 13-research-data-foundation-fixes
**Mode:** --auto (recommended option auto-selected for every question)
**Areas discussed:** Collector universe, History depth and backfill CLI, Universe freeze, Mark-price klines, Backfill robustness, Parquet→backtest builder

---

## Collector universe
| Option | Description | Selected |
|--------|-------------|----------|
| Live-5 ∪ top-15 by current volume, config file | Superset collected now; freeze later selects subset | ✓ |
| Wait for frozen manifest | Blocked: manifest needs backfilled data, and OI is lost each day | |
| Hard-code 12 symbols | Hand-picking, the defect D039 fixes | |

[auto] Collector universe — Q: "Which symbols does the collector track before the freeze?" → Selected: "Live-5 ∪ top-15, config file" (recommended default)

## History depth and backfill CLI
| Option | Description | Selected |
|--------|-------------|----------|
| 1m 12 months, 1H/4H 2 years | Top of the decided range; protects the unmeasured D043 trade floor | ✓ |
| 1m 6 months | Cheaper, more likely to fall short of the floor | |

[auto] Depth — Q: "How deep is 1m history?" → Selected: "12 months" (recommended default)
[auto] Trade-floor check — Q: "What does the CLI do on shortfall?" → Selected: "Report only, never lower the floor" (recommended default)

## Universe freeze
| Option | Description | Selected |
|--------|-------------|----------|
| Follow manifest procedure; explicit `--freeze` flag | Deliberate operator action, two hash witnesses in one commit | ✓ |
| Freeze automatically after backfill | Side-effect freeze, no review | |

[auto] Delisted symbols — Q: "Source for delisted contracts?" → Selected: "Verify REST first, fall back to public archive, report unavailable, never drop" (recommended default)

## Mark-price klines
[auto] Mark-price klines — Q: "Where do they live?" → Selected: "Separate Parquet dataset, same validation and atomic publish; ingestion only" (recommended default)

## Backfill robustness
[auto] Partial day — Q: "When may a day be published?" → Selected: "Only when closed; never the current UTC day" (recommended default)
[auto] Atomicity — Q: "How are files written?" → Selected: "tmp + os.replace, keep no-overwrite guard" (recommended default)
[auto] Zero-trade bars — Q: "Valid or rejected?" → Selected: "Valid; gaps remain gaps" (recommended default)
[auto] Supervisor — Q: "Order on reconnect?" → Selected: "Backfill before resubscribe" (recommended default)

## Parquet → backtest builder
[auto] Builder — Q: "How is dataset identity captured?" → Selected: "Per-file content hashes rolled into one dataset hash on the experiment record; refuse unresolved gaps" (recommended default)

## Claude's Discretion
Module/CLI/flag names, mark-kline partition layout, collect-list file format, pacing constants.

## Deferred Ideas
Simulator mark-price triggers (Phase 14); gate code (Phase 26); trade-count estimate (needs Phase 14); infra items (Phase 13.1).
