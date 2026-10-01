"""Tests for bundle verification and restore (Phase 13.1 plan 06, D-12 / D-13).

No PostgreSQL is needed: the pg_restore and migrate steps are injected fake
runners, and the database emptiness probe is a seam. The real pg_restore path
runs in the docker drill test of plan 10.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from src.ops import backup as backup_mod
from src.ops.backup import LibpqTarget, libpq_target, main, restore_bundle, verify_bundle

DB_URL = "postgresql+psycopg://trading:placeholder-pw@db:5432/trading"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_dump(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKE-PG-DUMP\x00" * 8)
    return out


def _make_bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Backup of a two-file Parquet root; returns (bundle_root, source_root)."""
    source = tmp_path / "raw"
    (source / "interval=1m" / "symbol=BTCUSDT").mkdir(parents=True)
    (source / "interval=1m" / "symbol=BTCUSDT" / "part.parquet").write_bytes(b"AAA" * 100)
    (source / "oi.parquet").write_bytes(b"BBB" * 100)
    bundle = tmp_path / "bundle"
    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])
    return bundle, source


class _Recorder:
    """Fake pg_restore and migrate runners that note what the target looked like."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.calls: list[str] = []
        self.files_at_pg_restore: list[str] | None = None
        self.hashes_at_migrate: dict[str, str] | None = None
        self.dump_seen: Path | None = None
        self.libpq_seen: LibpqTarget | None = None

    def _listing(self) -> list[str]:
        if not self.target.exists():
            return []
        return sorted(
            p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file()
        )

    def pg_restore(self, dump: Path, target: LibpqTarget) -> None:
        self.calls.append("pg_restore")
        self.files_at_pg_restore = self._listing()
        self.dump_seen = dump
        self.libpq_seen = target

    def migrate(self, url: str) -> None:
        self.calls.append("migrate")
        self.hashes_at_migrate = {rel: _sha(self.target / rel) for rel in self._listing()}


def _no_data(_url: str) -> list[str]:
    return []


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


def test_verify_clean_bundle_is_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, _ = _make_bundle(tmp_path)
    assert verify_bundle(bundle) == []
    assert main(["verify", "--bundle-root", str(bundle)]) == 0
    assert "verify-OK" in capsys.readouterr().out


def test_verify_flags_changed_byte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, source = _make_bundle(tmp_path)
    target = bundle / "parquet" / source.name / "oi.parquet"
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))

    assert main(["verify", "--bundle-root", str(bundle)]) == 1
    err = capsys.readouterr().err.splitlines()
    problem_lines = [line for line in err if f"parquet/{source.name}/oi.parquet" in line]
    assert len(problem_lines) == 1
    assert "sha256" in problem_lines[0]


def test_verify_flags_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, source = _make_bundle(tmp_path)
    (bundle / "parquet" / source.name / "oi.parquet").unlink()

    assert main(["verify", "--bundle-root", str(bundle)]) == 1
    err = capsys.readouterr().err
    assert f"parquet/{source.name}/oi.parquet" in err
    assert "missing" in err


def test_verify_flags_extra_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle, source = _make_bundle(tmp_path)
    (bundle / "parquet" / source.name / "stowaway.parquet").write_bytes(b"x")

    assert main(["verify", "--bundle-root", str(bundle)]) == 1
    err = capsys.readouterr().err
    assert f"parquet/{source.name}/stowaway.parquet" in err
    assert "not in manifest" in err


def test_verify_without_manifest_is_a_problem(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    problems = verify_bundle(bundle)
    assert len(problems) == 1
    assert "manifest.json" in problems[0]


def test_verify_rejects_path_traversal_keys(tmp_path: Path) -> None:
    bundle, _ = _make_bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parquet/raw/../../escape.parquet"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    problems = verify_bundle(bundle)
    assert any("unsafe" in p and "escape.parquet" in p for p in problems)


# --------------------------------------------------------------------------- #
# restore
# --------------------------------------------------------------------------- #


def _restore_argv(bundle: Path, target: Path, *extra: str) -> list[str]:
    return ["restore", "--bundle-root", str(bundle), "--parquet-target", str(target), *extra]


def test_restore_refuses_tampered_bundle_before_anything_happens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, source = _make_bundle(tmp_path)
    (bundle / "parquet" / source.name / "oi.parquet").write_bytes(b"TAMPERED")
    target = tmp_path / "restored"
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc != 0
    assert rec.calls == []
    assert not target.exists() or not any(target.iterdir())
    assert "oi.parquet" in capsys.readouterr().err


def test_restore_runs_pg_restore_then_copy_then_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, source = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc == 0
    assert rec.calls == ["pg_restore", "migrate"]
    # pg_restore ran while the Parquet target was still empty; migrate ran after the copy.
    assert rec.files_at_pg_restore == []
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    prefix = f"parquet/{source.name}/"
    expected = {k[len(prefix) :]: v for k, v in manifest.items() if k.startswith(prefix)}
    assert expected  # sanity
    assert rec.hashes_at_migrate == expected
    assert rec.dump_seen == bundle / "pg.dump"
    assert not [p for p in target.rglob("*.tmp")]


def test_restore_refuses_non_empty_target_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, _ = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "something.txt").write_text("keep me", encoding="utf-8")
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc != 0
    assert rec.calls == []
    assert (target / "something.txt").read_text(encoding="utf-8") == "keep me"


def test_restore_force_skips_identical_and_aborts_on_different_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    bundle, source = _make_bundle(tmp_path)
    prefix = bundle / "parquet" / source.name

    # Identical pre-existing file: skipped, restore succeeds.
    same_target = tmp_path / "same"
    same_target.mkdir()
    (same_target / "oi.parquet").write_bytes((prefix / "oi.parquet").read_bytes())
    rec = _Recorder(same_target)
    rc = main(
        _restore_argv(bundle, same_target, "--force"),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )
    assert rc == 0
    assert rec.calls == ["pg_restore", "migrate"]

    # Differing pre-existing file: restore aborts before pg_restore, file untouched.
    diff_target = tmp_path / "diff"
    diff_target.mkdir()
    (diff_target / "oi.parquet").write_bytes(b"DIFFERENT")
    rec2 = _Recorder(diff_target)
    rc2 = main(
        _restore_argv(bundle, diff_target, "--force"),
        pg_restore_runner=rec2.pg_restore,
        migrate_runner=rec2.migrate,
        data_probe=_no_data,
    )
    assert rc2 != 0
    assert rec2.calls == []
    assert (diff_target / "oi.parquet").read_bytes() == b"DIFFERENT"


def test_restore_skip_db_copies_parquet_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    bundle, _ = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    rec = _Recorder(target)

    rc = main(
        _restore_argv(bundle, target, "--skip-db"),
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )

    assert rc == 0
    assert rec.calls == []
    assert (target / "oi.parquet").exists()
    assert (target / "interval=1m" / "symbol=BTCUSDT" / "part.parquet").exists()


def test_restore_bundle_api_returns_counts(tmp_path: Path) -> None:
    bundle, _ = _make_bundle(tmp_path)
    target = tmp_path / "restored"
    rec = _Recorder(target)
    report = restore_bundle(
        bundle,
        parquet_target=target,
        database_url=DB_URL,
        force=False,
        skip_db=False,
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )
    assert report.copied == 2
    assert report.skipped == 0
    assert report.database_restored is True


# --------------------------------------------------------------------------- #
# Task 2: libpq URL handling, production runners, dump / restore-db, hygiene
# --------------------------------------------------------------------------- #

SECRET_PW = "p@ss-Wxyz-1234"
SECRET_URL = "postgresql+psycopg://trading:p%40ss-Wxyz-1234@postgres:5432/trading"


def test_libpq_target_strips_driver_and_moves_password() -> None:
    target = libpq_target(SECRET_URL)
    assert target.url_without_password == "postgresql://trading@postgres:5432/trading"
    assert target.env == {"PGPASSWORD": SECRET_PW}
    assert SECRET_PW not in repr(target)


def test_libpq_target_without_password_has_empty_env() -> None:
    target = libpq_target("postgresql://trading@postgres/trading?sslmode=require")
    assert target.url_without_password == "postgresql://trading@postgres/trading?sslmode=require"
    assert target.env == {}


def test_libpq_target_moves_password_query_parameter() -> None:
    target = libpq_target(
        "postgresql://trading@postgres/trading?password=qpw-123456&sslmode=disable"
    )
    assert "qpw-123456" not in target.url_without_password
    assert "sslmode=disable" in target.url_without_password
    assert target.env == {"PGPASSWORD": "qpw-123456"}


def test_libpq_target_rejects_other_schemes() -> None:
    with pytest.raises(ValueError) as excinfo:
        libpq_target("mysql://user:topsecret99@host/db")
    assert "mysql" in str(excinfo.value)
    assert "topsecret99" not in str(excinfo.value)


class _RunSpy:
    def __init__(self) -> None:
        self.argv: list[str] = []
        self.env: dict[str, str] = {}
        self.kwargs: dict[str, Any] = {}

    def __call__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = list(argv)
        self.kwargs = dict(kwargs)
        self.env = dict(kwargs.get("env") or {})


def test_prod_pg_dump_runner_keeps_password_off_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _RunSpy()
    monkeypatch.setattr(backup_mod.subprocess, "run", spy)
    monkeypatch.delenv("PG_DUMP_BIN", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)

    out = tmp_path / "pg.dump"
    assert backup_mod._prod_pg_dump_runner(out) == out

    joined = " ".join(spy.argv)
    assert spy.argv[0] == "pg_dump"
    assert "--format=custom" in spy.argv
    assert SECRET_PW not in joined
    assert "p%40ss" not in joined
    assert "+psycopg" not in joined
    assert "postgresql://trading@postgres:5432/trading" in spy.argv
    assert spy.env["PGPASSWORD"] == SECRET_PW
    assert spy.kwargs["check"] is True


def test_prod_pg_dump_runner_honours_pg_dump_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _RunSpy()
    monkeypatch.setattr(backup_mod.subprocess, "run", spy)
    monkeypatch.setenv("PG_DUMP_BIN", "/opt/pg17/bin/pg_dump")
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    backup_mod._prod_pg_dump_runner(tmp_path / "pg.dump")
    assert spy.argv[0] == "/opt/pg17/bin/pg_dump"


def test_prod_pg_dump_failure_text_has_no_password_or_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    def boom(argv: list[str], **_kw: Any) -> None:
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(backup_mod.subprocess, "run", boom)
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        backup_mod._prod_pg_dump_runner(tmp_path / "pg.dump")
    assert SECRET_PW not in str(excinfo.value)
    assert "--dbname" not in str(excinfo.value)
    assert "pg_dump" in str(excinfo.value)


def test_prod_pg_restore_runner_argv_and_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spy = _RunSpy()
    monkeypatch.setattr(backup_mod.subprocess, "run", spy)
    monkeypatch.delenv("PG_RESTORE_BIN", raising=False)
    dump = tmp_path / "pg.dump"
    backup_mod._prod_pg_restore_runner(dump, libpq_target(SECRET_URL))

    assert spy.argv[0] == "pg_restore"
    for flag in ("--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error"):
        assert flag in spy.argv
    assert spy.argv[-1] == str(dump)
    assert "postgresql://trading@postgres:5432/trading" in spy.argv
    assert SECRET_PW not in " ".join(spy.argv)
    assert spy.env["PGPASSWORD"] == SECRET_PW


def test_prod_pg_restore_failure_text_has_no_password_or_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    def boom(argv: list[str], **_kw: Any) -> None:
        raise subprocess.CalledProcessError(1, argv)

    monkeypatch.setattr(backup_mod.subprocess, "run", boom)
    with pytest.raises(RuntimeError) as excinfo:
        backup_mod._prod_pg_restore_runner(tmp_path / "pg.dump", libpq_target(SECRET_URL))
    assert SECRET_PW not in str(excinfo.value)
    assert "--dbname" not in str(excinfo.value)


def test_prod_migrate_runner_uses_alembic_with_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    spy = _RunSpy()
    monkeypatch.setattr(backup_mod.subprocess, "run", spy)
    backup_mod._prod_migrate_runner(SECRET_URL)
    assert spy.argv == [sys.executable, "-m", "alembic", "upgrade", "head"]
    assert spy.env["DATABASE_URL"] == SECRET_URL
    assert (Path(str(spy.kwargs["cwd"])) / "alembic.ini").exists()


def test_main_prints_calledprocesserror_without_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    def leaky(_out: Path) -> Path:
        raise subprocess.CalledProcessError(
            1, ["pg_dump", "--dbname", f"postgresql://trading:{SECRET_PW}@postgres/trading"]
        )

    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    monkeypatch.setattr(backup_mod, "_prod_pg_dump_runner", leaky)
    source = tmp_path / "raw"
    source.mkdir()
    (source / "a.parquet").write_bytes(b"a")

    rc = main(["backup", "--bundle-root", str(tmp_path / "b"), "--parquet-roots", str(source)])
    captured = capsys.readouterr()
    assert rc == 1
    assert SECRET_PW not in captured.err + captured.out
    assert "--dbname" not in captured.err
    assert "pg_dump" in captured.err


def test_main_scrubs_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def leaky(_out: Path) -> Path:
        raise RuntimeError(f"connection failed for password {SECRET_PW}")

    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.setattr(backup_mod, "_prod_pg_dump_runner", leaky)
    source = tmp_path / "raw"
    source.mkdir()
    (source / "a.parquet").write_bytes(b"a")
    rc = main(["backup", "--bundle-root", str(tmp_path / "b"), "--parquet-roots", str(source)])
    captured = capsys.readouterr()
    assert rc == 1
    assert SECRET_PW not in captured.err
    assert "[REDACTED]" in captured.err


def test_main_calls_configure_logging_first() -> None:
    import ast

    tree = ast.parse(Path(backup_mod.__file__).read_text(encoding="utf-8"))
    main_def = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    body = [
        stmt
        for stmt in main_def.body
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
    ]
    first = body[0]
    assert isinstance(first, ast.Expr)
    call = first.value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name) and call.func.id == "configure_logging"


def test_dump_writes_file_and_sha256_sidecar(tmp_path: Path) -> None:
    out = tmp_path / "old-host.dump"
    rc = main(["dump", "--out", str(out)], pg_dump_runner=_fake_dump)
    assert rc == 0
    sidecar = tmp_path / "old-host.dump.sha256"
    assert sidecar.read_text(encoding="utf-8") == f"{_sha(out)}  old-host.dump\n"


def test_restore_db_refuses_wrong_expected_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    dump = _fake_dump(tmp_path / "x.dump")
    rec = _Recorder(tmp_path / "unused")
    rc = main(
        ["restore-db", "--pg-dump", str(dump), "--expect-sha256", "0" * 64],
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )
    assert rc != 0
    assert rec.calls == []
    assert "sha256" in capsys.readouterr().err


def test_restore_db_runs_pg_restore_then_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    dump = _fake_dump(tmp_path / "x.dump")
    rec = _Recorder(tmp_path / "unused")
    rc = main(
        ["restore-db", "--pg-dump", str(dump), "--expect-sha256", _sha(dump).upper()],
        pg_restore_runner=rec.pg_restore,
        migrate_runner=rec.migrate,
        data_probe=_no_data,
    )
    assert rc == 0
    assert rec.calls == ["pg_restore", "migrate"]


def test_restore_database_refuses_non_empty_database_unless_force(tmp_path: Path) -> None:
    dump = _fake_dump(tmp_path / "x.dump")
    rec = _Recorder(tmp_path / "unused")
    with pytest.raises(backup_mod.RestoreRefused, match="not empty"):
        backup_mod.restore_database(
            dump,
            database_url=DB_URL,
            force=False,
            pg_restore_runner=rec.pg_restore,
            data_probe=lambda _u: ["collector_watermarks"],
        )
    assert rec.calls == []
    backup_mod.restore_database(
        dump,
        database_url=DB_URL,
        force=True,
        pg_restore_runner=rec.pg_restore,
        data_probe=lambda _u: ["collector_watermarks"],
    )
    assert rec.calls == ["pg_restore"]


def test_tables_with_rows_ignores_alembic_version_and_empty_tables(tmp_path: Path) -> None:
    import sqlite3

    db_file = tmp_path / "probe.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE alembic_version (version_num TEXT)")
    conn.execute("INSERT INTO alembic_version VALUES ('abc')")
    conn.execute("CREATE TABLE empty_table (x INTEGER)")
    conn.commit()
    conn.close()
    url = f"sqlite:///{db_file.as_posix()}"
    assert backup_mod._tables_with_rows(url) == []

    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE collector_watermarks (symbol TEXT)")
    conn.execute("INSERT INTO collector_watermarks VALUES ('BTCUSDT')")
    conn.commit()
    conn.close()
    assert backup_mod._tables_with_rows(url) == ["collector_watermarks"]


def test_backup_skips_atomic_write_temp_files(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "part.parquet").write_bytes(b"real")
    (source / ".part.parquet.4242.tmp").write_bytes(b"in-flight")
    (source / "sub").mkdir()
    (source / "sub" / ".other.parquet.7.tmp").write_bytes(b"in-flight")
    bundle = tmp_path / "bundle"

    backup_mod.backup(bundle_root=bundle, pg_dump_runner=_fake_dump, parquet_roots=[source])

    assert not list(bundle.rglob("*.tmp"))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert not [k for k in manifest if k.endswith(".tmp")]
    assert f"parquet/{source.name}/part.parquet" in manifest
    assert verify_bundle(bundle) == []


def test_write_manifest_skips_temp_files(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "a.parquet").write_bytes(b"a")
    (payload / ".a.parquet.1.tmp").write_bytes(b"tmp")
    manifest = backup_mod.write_manifest(payload, tmp_path / "manifest.json")
    assert list(manifest) == ["a.parquet"]


def test_pg_dump_runs_before_any_parquet_file_is_copied(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    source.mkdir()
    (source / "part.parquet").write_bytes(b"real")
    bundle = tmp_path / "bundle"
    seen: dict[str, list[str]] = {}

    def recording_runner(out: Path) -> Path:
        seen["files"] = sorted(p.name for p in bundle.rglob("*.parquet"))
        return _fake_dump(out)

    backup_mod.backup(bundle_root=bundle, pg_dump_runner=recording_runner, parquet_roots=[source])
    assert seen["files"] == []
    assert (bundle / "parquet" / source.name / "part.parquet").exists()
