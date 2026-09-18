# Implementation Plan

## Planning assumptions

The plan assumes one developer working primarily in evenings/weekends. Calendar durations are planning envelopes, not promises. Phase 0B runs in parallel with research/backtest work; later phases depend on their stated exit gates.

Expected overall path to first cautious live-approved order: approximately **15–24 months**, mainly because forward/paper evidence is time-limited by the strategy's signal frequency. Coding faster does not remove the need for forward evidence.

## Phase 0A — Research + strategy formalization

Planning envelope: 4–8 weeks.

Goal: produce one deterministic candidate strategy without committing to live execution.

Tasks:

1. Learn/formalize market structure.
2. Define candidate strategy families.
3. Define exact candidate entry/SL/TP rules.
4. Define research universe (may be 10–15 liquid symbols).
5. Define cost model and execution assumptions.
6. Define parameter registry and golden fixtures.
7. Record research decisions and anti-overfitting constraints.

Exit gate:

- candidate rule set is deterministic;
- all ambiguous definitions are resolved or explicitly marked `TBD`;
- research protocol is frozen for the candidate comparison.

## Phase 0B — Data foundation (starts immediately and runs in parallel)

Planning envelope: first 1–2 weeks for bootstrap; collectors then run continuously.

Tasks:

1. Create the Python 3.13 project (`pyproject.toml`, `uv`, test/lint/type-check configuration).
2. Bootstrap 1m/1H/4H historical candles.
2. Start the OI collector immediately.
3. Start/refresh funding history collection.
4. Persist exchange symbol metadata and observed constraints.
5. Add continuity/quality checks.
6. Add automated database backup.

Exit gate:

- raw data is persisted and queryable;
- OI collector is running continuously;
- backup/restore smoke test passes.

This phase must not wait for the final strategy.

## Phase 1 — Backtest engine

Planning envelope: 6–10 weeks.

Build:

- historical data reader;
- feature engine;
- strategy runner;
- execution simulator;
- limit-fill model;
- intrabar resolution;
- cost model;
- quantization model;
- metrics and uncertainty analysis;
- experiment registry;
- golden fixtures.

Exit gate:

- reproducible backtest;
- no-lookahead suite passes;
- same quantization logic is used in backtest and live planner;
- baseline comparisons are generated;
- bootstrap/Monte Carlo uncertainty report is available.

## Phase 2 — Realtime paper signal engine

Planning envelope: 3–6 months of forward observation, plus implementation time.

Build:

- Binance WebSocket market data;
- warm-up/reconnect/resync;
- strategy engine;
- trade planner;
- risk engine;
- signal journal;
- Telegram notifications;
- system-vs-user opportunity reports.

No live orders.

Exit gate:

- minimum forward evidence defined by the actual signal frequency;
- no unexplained data gaps;
- no material divergence between paper implementation and backtest assumptions;
- operational runbook exercised.

## Phase 3 — Human-approved live

Planning envelope: 4–8 weeks initial controlled rollout.

Add:

- Binance order manager;
- approval idempotency;
- limit entry;
- Algo Order protective exits;
- live reconciliation;
- orphan-order sweeper;
- exchange-constraint snapshots.

Start with the smallest capital that is operationally meaningful and within the declared research budget.

Exit gate:

- no unexplained reconciliation drift;
- no duplicate execution incidents;
- protective-order verification works;
- backups/restores work;
- manual emergency procedure has been rehearsed.

## Phase 4 — Research expansion

Possible future work:

- OI as strategy feature;
- funding as strategy feature;
- 15M refinement;
- portfolio correlation model;
- additional strategy families.

Every addition must be compared against the frozen baseline.

## Phase 5 — Autonomous execution (future, not committed)

Not planned for initial build.

Requires a separate decision record and evidence that:

- strategy is stable;
- risk controls are reliable;
- execution is reliable;
- human-approved operation has a sufficient sample;
- failure modes are understood.

## Project kill gate

Per `DECISIONS.md` D013:

If **3 independently specified candidate strategy families** have been tested under the frozen methodology and **at least 6 months** of research have elapsed without a candidate passing the acceptance methodology, stop adding strategy complexity.

The project then becomes a research/journal platform with live trading disabled until a new evidence-backed research question is approved.

A `NO_TRADE` conclusion is a valid research outcome.


## Python implementation notes

The implementation phases assume one Python codebase shared by research, backtest, paper, and live orchestration. Research notebooks are consumers of the same package code, not a second implementation.

The first repository bootstrap should establish:

```text
pyproject.toml
src/
research/
tests/
Dockerfile
```

and automated checks for test, lint/format, and type validation.
