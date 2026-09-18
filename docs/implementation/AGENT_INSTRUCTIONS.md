# Coding Agent Instructions

These rules are intended for vibe-coding/agentic coding sessions.

## 1. Do not invent trading rules

If a requested implementation needs a missing trading definition, reference `TRADING_STRATEGY_SPEC.md` and mark the requirement as `TBD` rather than inventing it.

## 2. No AI decision path

Do not add LLM/API calls to choose:

- direction,
- entry,
- stop,
- target,
- size,
- risk state.

## 3. Research/spec/code separation

```text
Research → Strategy Spec → Code
```

Do not patch strategy logic directly in production code as an experiment.

## 4. Tests required for strategy code

Every deterministic strategy function should have tests for:

- positive case,
- negative case,
- boundary conditions,
- candle-close timing,
- no-lookahead behavior,
- invalidation,
- expiry.

## 5. Reproducibility

A backtest must be rerunnable from:

- code version,
- data version/range,
- strategy version,
- parameters,
- cost assumptions.

## 6. Live execution safety

No live order code may be enabled by default.

Any code touching live order endpoints must have:

- explicit environment guard,
- dry-run/paper path,
- structured logging,
- reconciliation,
- idempotency,
- protective-order verification.

## 7. Change discipline

When changing strategy logic:

1. update research/spec,
2. create strategy version,
3. update tests,
4. rerun backtests,
5. record decision.

## 8. Avoid premature complexity

Do not introduce Kafka, ML, order-book reconstruction, or a large microservice topology unless a documented requirement justifies it.

## 9. Canonical documentation sources

Before changing code, read:

1. `GLOSSARY.md`
2. `data/DATA_MODEL.md`
3. `configuration/CONFIGURATION.md`
4. `testing/TESTING_STRATEGY.md`
5. relevant strategy/execution/risk docs.

Do not create new status enums, persistence entities, or parameter storage conventions when a canonical document already defines them.

## 10. Missing-contract behavior

If a required rule is missing from the docs:

```text
STOP
→ mark TBD
→ create a research/spec task
→ do not invent production behavior
```


## 11. Python-specific agent rules

- Treat `TECHNOLOGY_STACK.md` as the canonical language/tooling decision.
- Use Python 3.13 unless a decision record explicitly changes the baseline.
- Use `pyproject.toml` and the repository's documented environment/task tool; do not create ad-hoc virtualenv conventions per task.
- Do not put strategy semantics inside notebooks. Notebooks must call library code.
- Keep strategy functions deterministic and free of network/database side effects.
- Do not pass pandas/Polars DataFrames directly through the live domain unless the contract explicitly defines them; normalize to domain types at the boundary.
- Use `Decimal` or tick/step integer arithmetic for exchange-sensitive order values where specified by the domain contract.
- Prefer the current official Binance Python SDK for supported API surfaces; wrap it behind adapters.
- Any new Python dependency must be justified against `TECHNOLOGY_STACK.md` and added to `pyproject.toml`.
