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
from dataclasses import dataclass, field
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

# Known column-type heads (expanded: the old list missed BIGINT/JSONB/UUID
# and let type/nullability/PK drift pass as "parity green").
_KNOWN_TYPES = (
    "VARCHAR",
    "CHAR",
    "TEXT",
    "TIMESTAMP",
    "NUMERIC",
    "DECIMAL",
    "INTEGER",
    "INT",
    "BIGINT",
    "SMALLINT",
    "BOOLEAN",
    "BOOL",
    "DATE",
    "TIME",
    "JSONB",
    "JSON",
    "UUID",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "BYTEA",
    "INTERVAL",
)

_COL_LINE = re.compile(r"""^["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s+(.+?)\s*,?\s*$""")


def _norm_spec(raw: str) -> str:
    """Normalize a column definition tail (`VARCHAR(32) NOT NULL`)."""
    return re.sub(r"\s+", " ", raw.strip().rstrip(",")).upper()


@dataclass
class _TableSpec:
    """Full column spec for one table: name → normalized definition."""

    columns: dict[str, str] = field(default_factory=dict)
    pk: tuple[str, ...] = ()


def _parse_create_tables(sql: str) -> tuple[dict[str, _TableSpec], list[str]]:
    """Parse every `CREATE TABLE` block into full column specs.

    Returns (tables, unparsed_lines). Unparsed non-blank lines are
    returned — never silently ignored — so the caller fails loudly.
    """
    tables: dict[str, _TableSpec] = {}
    unparsed: list[str] = []
    current: str | None = None
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        create = re.match(r"CREATE TABLE\s+(.+?)\s*\(\s*$", stripped, re.IGNORECASE)
        if create:
            # Schema-qualified names ("public"."collector_gaps") resolve to
            # the bare table name.
            current = create.group(1).split(".")[-1].strip('"').strip("'")
            tables[current] = _TableSpec()
            continue
        if current is None:
            continue
        if stripped in (");", ")"):
            current = None
            continue
        spec = tables[current]
        pk_match = re.match(
            r"(?:CONSTRAINT\s+\S+\s+)?PRIMARY KEY\s*\(([^)]+)\)",
            stripped,
            re.IGNORECASE,
        )
        if pk_match:
            cols = tuple(c.strip().strip('"').strip("'") for c in pk_match.group(1).split(","))
            spec.pk = cols
            continue
        if re.match(r"(?:CONSTRAINT|FOREIGN KEY|UNIQUE|CHECK)\b", stripped, re.IGNORECASE):
            continue
        assert current is not None  # narrowed: `current is None` continues above
        m = _COL_LINE.match(stripped)
        type_head = m.group(2).strip().split()[0].split("(")[0].upper() if m else ""
        if m and type_head in _KNOWN_TYPES:
            name = m.group(1)
            norm = _norm_spec(m.group(2))
            spec.columns[name] = norm
            if "PRIMARY KEY" in norm:
                spec.pk = (*spec.pk, name)
            continue
        unparsed.append(line)
    return tables, unparsed


def _render_migration_ddl() -> tuple[dict[str, _TableSpec], list[str]]:
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

    return _parse_create_tables(buf.getvalue())


def main() -> int:
    engine = create_engine("postgresql+psycopg://placeholder")

    # Render model DDL → full column specs (name, type, nullability, PK).
    model_tables: dict[str, _TableSpec] = {}
    model_unparsed: list[str] = []
    for tbl in Base.metadata.sorted_tables:
        ddl = str(CreateTable(tbl).compile(engine))
        parsed, bad = _parse_create_tables(ddl)
        model_tables[tbl.name] = parsed.get(tbl.name, _TableSpec(columns={}, pk=()))
        model_unparsed.extend(bad)

    migration_tables, migration_unparsed = _render_migration_ddl()

    failures: list[str] = []
    # Unparsed DDL lines are never ignored — an unknown line shape means
    # the parser (not the schema) is blind, and must fail loudly.
    for line in model_unparsed:
        failures.append(f"model DDL line not parsed: {line.strip()!r}")
    for line in migration_unparsed:
        failures.append(f"migration DDL line not parsed: {line.strip()!r}")

    # Alembic's bookkeeping table (`alembic_version`) is auto-created by
    # Alembic at upgrade time — exclude it from the parity check.
    skip = {"alembic_version"}
    all_tables = (set(model_tables) | set(migration_tables)) - skip
    for tbl in sorted(all_tables):
        model_spec = model_tables.get(tbl)
        migration_spec = migration_tables.get(tbl)
        if model_spec is None:
            failures.append(f"{tbl}: present in migration, missing from models")
            continue
        if migration_spec is None:
            failures.append(f"{tbl}: present in models, missing from migration")
            continue
        model_cols = set(model_spec.columns)
        migration_cols = set(migration_spec.columns)
        for col in sorted(model_cols - migration_cols):
            failures.append(f"{tbl}.{col}: model-only column")
        for col in sorted(migration_cols - model_cols):
            failures.append(f"{tbl}.{col}: migration-only column")
        for col in sorted(model_cols & migration_cols):
            if model_spec.columns[col] != migration_spec.columns[col]:
                failures.append(
                    f"{tbl}.{col}: type/nullability drift "
                    f"(model {model_spec.columns[col]!r} vs "
                    f"migration {migration_spec.columns[col]!r})"
                )
        if tuple(model_spec.pk) != tuple(migration_spec.pk):
            failures.append(
                f"{tbl}: PK drift (model {model_spec.pk} vs migration {migration_spec.pk})"
            )

    if failures:
        print("SCHEMA DRIFT DETECTED:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print("OK — model <-> migration parity green:")
    for tbl in sorted(all_tables):
        cols = sorted(model_tables[tbl].columns)
        print(f"  {tbl} ({len(cols)} cols, pk={model_tables[tbl].pk}): {cols}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
