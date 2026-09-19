"""Structural verification: model DDL <-> migration DDL.

Imports both `Base.metadata` and the migration's upgrade ops, compares the
column sets each defines, and asserts parity. Catches schema drift between
`src/db/models.py` and `src/db/alembic/versions/0001_baseline.py` without
needing a live PG — used as a smoke check at plan close + during code
review.

Run: `uv run python scripts/check_migration_parity.py`
"""

from __future__ import annotations

import io
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

# Ensure repo root is on sys.path when run as a plain script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Stub DATABASE_URL — needed by env.py if alembic ops run; harmless otherwise.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://trading:placeholder@localhost:5432/trading"
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402
from src.db.models import Base  # noqa: E402

# Match `<colname> TYPE` lines inside `CREATE TABLE (...)`. Names may be
# quoted (alembic-emitted DDL) or unquoted (SQLAlchemy-compiled DDL).
_COL_NAME = re.compile(
    r"""^\s*["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s+(VARCHAR|TIMESTAMP|NUMERIC|INTEGER|BOOLEAN|TEXT|DATE)""",
    re.MULTILINE,
)


def _column_names_from_ddl(ddl: str) -> set[str]:
    """Extract column names from a `CREATE TABLE` DDL string."""
    return {m.group(1) for m in _COL_NAME.finditer(ddl)}


def _render_migration_ddl() -> dict[str, set[str]]:
    """Render the head migration's `CREATE TABLE` SQL to stdout, then parse."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "src/db/alembic")
    cfg.set_main_option(
        "sqlalchemy.url", "postgresql+psycopg://trading:placeholder@localhost/trading"
    )

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            command.upgrade(cfg, "head", sql=True)
    except SystemExit:
        pass

    sql = buf.getvalue()
    tables: dict[str, set[str]] = {}
    current: str | None = None
    for line in sql.splitlines():
        stripped = line.strip().rstrip(",")
        if stripped.startswith("CREATE TABLE "):
            current = stripped.split()[2].strip('"')
            tables[current] = set()
            continue
        if current is None:
            continue
        m = _COL_NAME.match(stripped)
        if m:
            tables[current].add(m.group(1))
        # End of CREATE TABLE block
        if line.strip() == ");":
            current = None
    return tables


def main() -> int:
    engine = create_engine("postgresql+psycopg://placeholder")

    # Render model DDL
    model_columns: dict[str, set[str]] = {}
    for tbl in Base.metadata.sorted_tables:
        ddl = str(CreateTable(tbl).compile(engine))
        model_columns[tbl.name] = _column_names_from_ddl(ddl)

    migration_columns = _render_migration_ddl()

    drift: list[tuple[str, set[str], set[str]]] = []
    # Alembic's bookkeeping table (`alembic_version`) is auto-created by
    # Alembic at upgrade time — exclude it from the parity check.
    skip = {"alembic_version"}
    all_tables = (set(model_columns) | set(migration_columns)) - skip
    for tbl in sorted(all_tables):
        m = model_columns.get(tbl, set())
        mig = migration_columns.get(tbl, set())
        if m != mig:
            drift.append((tbl, m - mig, mig - m))

    if drift:
        print("SCHEMA DRIFT DETECTED:")
        for tbl, model_only, migration_only in drift:
            print(f"  {tbl}:")
            if model_only:
                print(f"    model-only columns: {sorted(model_only)}")
            if migration_only:
                print(f"    migration-only columns: {sorted(migration_only)}")
        return 1

    print("OK — model <-> migration parity green:")
    for tbl in sorted(all_tables):
        cols = sorted(model_columns.get(tbl, set()))
        print(f"  {tbl} ({len(cols)} cols): {cols}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
