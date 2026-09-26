# Phase 6 — COVERAGE: external API integration scan

No external API integration: Phase 6 consumes Parquet data via in-repo `src/data/` adapters and calls in-repo `src/core/` + `src/risk/` functions; the simulator never imports the Binance SDK, makes no network calls, and adds no packages (stdlib + Decimal only inside execution semantics per D-05).
