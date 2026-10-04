# Tech stack

- Python `==3.13.*` (do not move to 3.14), managed by `uv` (`uv.lock` is the reproducibility mechanism; CI uses `uv sync --frozen --extra dev`).
- asyncio; official `binance-sdk-derivatives-trading-usds-futures>=17.3,<18` behind adapters (legacy binance-connector forbidden); python-telegram-bot 22.x; httpx 0.28.x.
- PostgreSQL 17 (operational) via SQLAlchemy 2.0.x + psycopg3 + Alembic; Parquet (`data/raw`) + DuckDB 1.5.5 + Polars 1.x + pyarrow for research.
- pydantic v2 + pydantic-settings; tenacity; structlog; tzdata (Windows).
- Dev: pytest 9 + pytest-asyncio (auto mode), respx, ruff (line-length 100, rules E,W,F,I,B,UP), mypy strict (`mypy src`).
- Docker Compose packaging (profiles: paper, live, ops); deploy scripts in `deploy/`.
- Dev machine is Windows (Git Bash + PowerShell); CI/VPS are Linux.
