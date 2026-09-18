# Architecture / Strategy Decision Log

| ID | Decision | Status | Rationale |
|---|---|---|---|
| D001 | No AI/LLM in trading decision core | Accepted | Deterministic, reproducible, backtestable, avoids stale-context subjective predictions |
| D002 | Binance is canonical execution/data source | Accepted | Trading occurs on Binance and exchange state must be authoritative |
| D003 | TradingView is optional research/cross-check adapter | Accepted | Useful for Pine/visual verification without coupling execution to it |
| D004 | Human approval before early live execution | Accepted | User is unavailable continuously and wants explicit control |
| D005 | Primary strategy TF 4H + 1H | Accepted provisionally | Fits limited screen time and avoids 5M dependency |
| D006 | 15M/5M are optional, not V1 core | Accepted provisionally | Short TTL signals are poorly matched to full-time work |
| D007 | Signal != trade plan != order != position | Accepted | Prevents coupling and supports system-vs-user analytics |
| D008 | Backtest before paper/live | Accepted | Avoid collecting live samples to answer a historical question |
| D009 | Collect OI independently from day one if possible | Accepted | Binance historical OI window is limited; self-collected history compounds in value |
| D010 | No fixed daily profit target | Accepted | Avoids forced trading |
| D011 | V1 likely limit-zone execution for swing setups | Provisional | Better fit for limited availability; strategy-specific expiry/invalidation required |
| D012 | Strategy V1 family | TBD | Research must decide |
| D013 | Strategy research kill gate | Provisional | After 3 independently specified candidate families AND at least 6 months of research, if none passes the acceptance methodology, stop adding strategy complexity, keep live trading disabled, and classify the project as a research/journal platform until a new evidence-backed question is approved |
| D014 | Canonical domain data model | Accepted | `data/DATA_MODEL.md` is the single persistence contract; Signal, TradePlan, Approval, Order, Fill, Position, and JournalEvent are separate entities |
| D015 | Canonical strategy parameter registry | Accepted | `configuration/CONFIGURATION.md`; every backtest/live plan is linked to immutable `parameterSetId` + `parameterSetHash` |
| D016 | Canonical enums and terminology | Accepted | `GLOSSARY.md` is the only source of truth for statuses/rejection reasons |
| D017 | Data collection starts in Phase 0 | Accepted | OI is time-sensitive historical data; collection begins immediately in parallel with research, while historical candles/funding can be bootstrapped later |

| D018 | Primary implementation language: Python | Accepted | Research, backtesting, realtime orchestration and human-approved execution share one language; the workload is low-frequency/research-heavy rather than HFT |
| D019 | Python runtime baseline: 3.13 | Accepted | Conservative stable baseline with broad third-party compatibility; evaluate 3.14 only after dependency verification |
| D020 | Research storage: Parquet + DuckDB; operational state: PostgreSQL | Accepted | Separates analytical historical data from transactional lifecycle state and avoids forcing one database to serve both roles |
| D021 | `pyproject.toml` + `uv` are the project tooling baseline | Accepted | Reproducible environments, dependency/task management, and agent-friendly project setup |
