"""Pure journal-depth analytics package (Phase 10, plan 10-01).

Per D-01: this package is read-only analytics. It imports stdlib + Decimal +
in-repo pure modules only (no Polars/pandas/NumPy/SQLAlchemy/Pydantic/FastAPI/
Binance SDK/Telegram, no adapters or DB), never writes operational tables, and
never feeds back into strategy, risk, or parameters. Modules are imported by
full path; this barrel holds no logic and no re-exports.
"""
