# Commands (run from repo root)

- Install: `uv sync --frozen --extra dev`
- Tests (CI form): `uv run pytest -m "not docker" -rs -p no:cacheprovider`; docker-marked tests need a daemon: `uv run pytest -m docker`
- Single file: `uv run pytest tests/test_backtest_simulator.py -q`
- Lint/format: `uv run ruff check`, `uv run ruff format --check` (drop `--check` to apply)
- Types: `uv run mypy src`
- Lock check: `uv lock --check`
- Compose validation: `docker compose config -q`
- Doc/protocol pins: `python scripts/verify_decision_alignment.py`
- GSD tooling: `gsd-tools query <verb>` (npm global); `loop render-hooks` is not supported in this install.
- Windows: no `make`; backtest-related test files are slow (~3 min locally), CI timeout 30 min.
