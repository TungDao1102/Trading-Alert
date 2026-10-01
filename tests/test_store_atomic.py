"""Atomic immutable Parquet publish (D-14, F-408).

`atomic_write_parquet` writes a same-directory temporary file, fsyncs it and
`os.replace`s it into place, so an interrupted write leaves neither a torn
`part.parquet` nor a stray temporary file. Immutability (D-04) is kept by an
explicit existence check because `os.replace` silently overwrites.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from src.adapters.binance_usdm import Kline
from src.data import store

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
BASE_MS = 1_699_920_000_000  # 2023-11-14T00:00Z
HOUR_MS = 3_600_000


def _frame() -> pl.DataFrame:
    return pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})


def _bar(index: int, *, symbol: str = "BTCUSDT", interval: str = "1h") -> Kline:
    open_ms = BASE_MS + index * HOUR_MS
    price = Decimal("100.00")
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_EPOCH + timedelta(milliseconds=open_ms),
        close_time_utc=_EPOCH + timedelta(milliseconds=open_ms + HOUR_MS - 1),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1.0"),
        quote_volume=price,
        trade_count=10,
    )


def _leftovers(directory: Path, *, keep: str = "part.parquet") -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name != keep)


def test_atomic_write_leaves_only_the_target(tmp_path: Path) -> None:
    target = tmp_path / "part.parquet"

    store.atomic_write_parquet(_frame(), target)

    assert_frame_equal(pl.read_parquet(target), _frame())
    assert [p.name for p in tmp_path.iterdir()] == ["part.parquet"]


def test_temporary_name_never_matches_the_part_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tmp name starts with '.' and ends with '.tmp' (readers glob part.parquet)."""
    seen: list[str] = []
    real_write = pl.DataFrame.write_parquet

    def _spy(self: pl.DataFrame, file: Path, *args: object, **kwargs: object) -> None:
        seen.append(Path(file).name)
        real_write(self, file, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _spy)

    store.atomic_write_parquet(_frame(), tmp_path / "part.parquet")

    assert len(seen) == 1
    assert seen[0].startswith(".")
    assert seen[0].endswith(".tmp")
    assert seen[0] != "part.parquet"


def test_interrupted_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash after partial bytes hit the temp file leaves nothing behind."""

    def _torn(self: pl.DataFrame, file: Path, *args: object, **kwargs: object) -> None:
        Path(file).write_bytes(b"PAR1-partial-bytes")
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _torn)
    target = tmp_path / "part.parquet"

    with pytest.raises(OSError, match="simulated crash"):
        store.atomic_write_parquet(_frame(), target)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_failed_replace_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store.os, "replace", _boom)
    target = tmp_path / "part.parquet"

    with pytest.raises(OSError, match="simulated replace failure"):
        store.atomic_write_parquet(_frame(), target)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_transient_permission_error_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows can refuse a replace while a scanner holds the file: bounded retry."""
    real_replace = store.os.replace
    attempts: list[int] = []
    sleeps: list[float] = []

    def _flaky(src: object, dst: object) -> None:
        attempts.append(1)
        if len(attempts) <= 2:
            raise PermissionError("simulated sharing violation")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(store.os, "replace", _flaky)
    monkeypatch.setattr(store.time, "sleep", sleeps.append)
    target = tmp_path / "part.parquet"

    store.atomic_write_parquet(_frame(), target)

    assert_frame_equal(pl.read_parquet(target), _frame())
    assert sleeps == [store.REPLACE_RETRY_SLEEP_SECONDS] * 2
    assert [p.name for p in tmp_path.iterdir()] == ["part.parquet"]


def test_persistent_permission_error_fails_closed_after_bounded_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[int] = []

    def _always(src: object, dst: object) -> None:
        attempts.append(1)
        raise PermissionError("simulated sharing violation")

    monkeypatch.setattr(store.os, "replace", _always)
    monkeypatch.setattr(store.time, "sleep", lambda _s: None)
    target = tmp_path / "part.parquet"

    with pytest.raises(PermissionError):
        store.atomic_write_parquet(_frame(), target)

    assert len(attempts) == store.REPLACE_MAX_ATTEMPTS
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_existing_file_is_never_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "part.parquet"
    target.write_bytes(b"original-immutable-bytes")

    with pytest.raises(FileExistsError):
        store.atomic_write_parquet(_frame(), target)

    assert target.read_bytes() == b"original-immutable-bytes"
    assert [p.name for p in tmp_path.iterdir()] == ["part.parquet"]


def test_publish_after_a_simulated_crash_matches_a_clean_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = [_bar(i) for i in range(4)]
    clean_root = tmp_path / "clean"
    crash_root = tmp_path / "crash"
    store.publish_batch(bars, interval="1h", symbol="BTCUSDT", raw_root=clean_root)

    with monkeypatch.context() as patched:

        def _torn(self: pl.DataFrame, file: Path, *args: object, **kwargs: object) -> None:
            Path(file).write_bytes(b"PAR1-partial-bytes")
            raise OSError("simulated crash mid-write")

        patched.setattr(pl.DataFrame, "write_parquet", _torn)
        with pytest.raises(OSError, match="simulated crash"):
            store.publish_batch(bars, interval="1h", symbol="BTCUSDT", raw_root=crash_root)

    day = datetime(2023, 11, 14).date()
    partition = store.partition_path(crash_root, "1h", "BTCUSDT", day)
    assert not (partition / "part.parquet").exists()
    assert list(partition.iterdir()) == []

    store.publish_batch(bars, interval="1h", symbol="BTCUSDT", raw_root=crash_root)

    assert_frame_equal(
        pl.read_parquet(store.partition_file(crash_root, "1h", "BTCUSDT", day)),
        pl.read_parquet(store.partition_file(clean_root, "1h", "BTCUSDT", day)),
    )


def test_publish_batch_still_refuses_an_existing_partition(tmp_path: Path) -> None:
    bars = [_bar(i) for i in range(3)]
    store.publish_batch(bars, interval="1h", symbol="BTCUSDT", raw_root=tmp_path)

    with pytest.raises(FileExistsError):
        store.publish_batch(bars, interval="1h", symbol="BTCUSDT", raw_root=tmp_path)


def test_publish_batch_still_rejects_heterogeneous_batches(tmp_path: Path) -> None:
    mixed = [_bar(0), _bar(1, symbol="ETHUSDT")]

    with pytest.raises(ValueError, match="heterogeneous"):
        store.publish_batch(mixed, interval="1h", symbol="BTCUSDT", raw_root=tmp_path)

    assert not any(tmp_path.rglob("*.parquet"))
