"""CLI tests for scripts/smoke_backtest_realdata.py (Phase 14, plan 14-14, D-17, D-26, D-31).

The script is a local measurement tool, but its argument handling, determinism check and
credential safety are CI-safe: every test here publishes a tiny synthetic raw root through
the real writers and never touches the network or a real database.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import smoke_backtest_realdata as smoke

from tests.backtest_case_helpers import constraint_row
from tests.test_case_input_builder import build_store

SYMBOL = "BTCUSDT"
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 3, tzinfo=UTC)  # exclusive: two whole UTC days, 07-01 and 07-02

_DIGEST_LINE = re.compile(r"^digest=([0-9a-f]{64})$", re.MULTILINE)


@pytest.fixture(scope="module")
def raw_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("smoke_store") / "raw"
    build_store(root, start=START, end=END, symbols=(SYMBOL,))
    return root


@pytest.fixture
def constraints_json(tmp_path: Path) -> Path:
    path = tmp_path / "constraints.json"
    rows = [constraint_row(SYMBOL, datetime(2026, 6, 1, tzinfo=UTC))]
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _base_args(raw_root: Path) -> list[str]:
    return [
        "--symbol",
        SYMBOL,
        "--days",
        "2",
        "--end-day",
        "2026-07-02",
        "--raw-root",
        str(raw_root),
    ]


def test_synthetic_root_runs_twice_with_matching_digests(
    raw_root: Path, constraints_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = smoke.main([*_base_args(raw_root), "--constraints-json", str(constraints_json)])
    out = capsys.readouterr().out

    assert code == 0
    digests = _DIGEST_LINE.findall(out)
    assert len(digests) == 2
    assert digests[0] == digests[1]
    for key in (
        "runtime_seconds",
        "tracemalloc_peak_bytes",
        "rss_peak",
        "trade_count",
        "end_of_data_count",
        "no_trade_counts",
        "dataset_id",
    ):
        assert len(re.findall(rf"^{key}=", out, flags=re.MULTILINE)) == 2, key
    assert re.search(r"^dataset_id=[0-9a-f]{64}$", out, flags=re.MULTILINE)


def _copy_without(raw_root: Path, dest_root: Path, *, drop: Path) -> Path:
    """A private copy of the store with the `drop` subtree (relative to the root) removed."""
    dest = dest_root / "raw"
    shutil.copytree(raw_root, dest)
    target = dest / drop
    assert target.exists(), target
    shutil.rmtree(target)
    return dest


def test_store_without_open_interest_still_runs(
    raw_root: Path,
    constraints_json: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """OI is not consumed by the v2 engine, so a store with no OI partitions must build.

    The real local store has no 90-day OI history (the Binance OI statistics endpoint serves
    about 30 days), so the smoke script deliberately does not request the series.
    """
    no_oi = _copy_without(raw_root, tmp_path, drop=Path("data_class=oi"))

    code = smoke.main([*_base_args(no_oi), "--constraints-json", str(constraints_json)])
    out = capsys.readouterr().out

    assert code == 0
    digests = _DIGEST_LINE.findall(out)
    assert len(digests) == 2
    assert digests[0] == digests[1]


@pytest.mark.parametrize(
    "drop",
    [
        Path("interval=1m") / f"symbol={SYMBOL}" / "date=2026-07-02",
        Path("dataset=mark_klines") / "interval=1m" / f"symbol={SYMBOL}" / "date=2026-07-02",
    ],
    ids=["trade_1m_day_missing", "mark_1m_day_missing"],
)
def test_hole_in_a_requested_series_still_fails_closed(
    raw_root: Path,
    constraints_json: Path,
    tmp_path: Path,
    drop: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Skipping OI hides nothing: the requested series keep failing closed (D-19)."""
    holed = _copy_without(raw_root, tmp_path, drop=drop)

    code = smoke.main([*_base_args(holed), "--constraints-json", str(constraints_json)])
    captured = capsys.readouterr()

    assert code == 3
    assert not _DIGEST_LINE.search(captured.out)
    assert "CaseInputGapError" in captured.err


def test_missing_constraint_source_fails_closed_with_exit_2(
    raw_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = smoke.main(_base_args(raw_root))
    captured = capsys.readouterr()

    assert code == 2
    assert not _DIGEST_LINE.search(captured.out)
    assert "constraint" in (captured.out + captured.err).lower()


def test_both_constraint_sources_are_refused(
    raw_root: Path, constraints_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = smoke.main(
        [
            *_base_args(raw_root),
            "--constraints-json",
            str(constraints_json),
            "--database-url-env",
            "SMOKE_TEST_DB_URL",
        ]
    )
    capsys.readouterr()

    assert code == 2


def test_unset_database_env_is_a_non_zero_exit_without_leaking(
    raw_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SMOKE_TEST_DB_URL_UNSET", raising=False)

    code = smoke.main([*_base_args(raw_root), "--database-url-env", "SMOKE_TEST_DB_URL_UNSET"])
    captured = capsys.readouterr()

    assert code != 0
    assert "postgresql://" not in captured.out + captured.err
    assert not _DIGEST_LINE.search(captured.out)


def test_unreachable_database_prints_the_exception_type_only(
    raw_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "S3cr3tPw-do-not-print"
    url = f"postgresql://smoke_user:{secret}@127.0.0.1:1/smoke_db"
    monkeypatch.setenv("SMOKE_TEST_DB_URL", url)
    monkeypatch.setattr(smoke, "DB_CONNECT_TIMEOUT_SECONDS", 1)

    code = smoke.main([*_base_args(raw_root), "--database-url-env", "SMOKE_TEST_DB_URL"])
    text = capsys.readouterr()
    combined = text.out + text.err

    assert code != 0
    assert secret not in combined
    assert "postgresql://" not in combined
    assert "smoke_user" not in combined
    assert "127.0.0.1" not in combined


def test_malformed_database_url_prints_the_exception_type_only(
    raw_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "S3cr3tPw-do-not-print"
    monkeypatch.setenv("SMOKE_TEST_DB_URL", f"postgresql://smoke_user:{secret}@db-host:notaport/x")

    code = smoke.main([*_base_args(raw_root), "--database-url-env", "SMOKE_TEST_DB_URL"])
    text = capsys.readouterr()
    combined = text.out + text.err

    assert code != 0
    assert secret not in combined
    assert "postgresql://" not in combined
    assert "smoke_user" not in combined
    assert "db-host" not in combined


@pytest.mark.parametrize(
    "bad",
    [
        ["--symbol", "../BTCUSDT"],
        ["--symbol", "btcusdt"],
        ["--days", "0"],
        ["--end-day", "not-a-date"],
        ["--equity", "ten"],
        ["--risk-rate", "0.5e-2x"],
    ],
)
def test_invalid_arguments_exit_2(
    raw_root: Path,
    constraints_json: Path,
    bad: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _base_args(raw_root)
    flag = bad[0]
    # Replace the flag's value when the base already carries it, else append.
    if flag in args:
        index = args.index(flag)
        args[index + 1] = bad[1]
    else:
        args += bad
    code = smoke.main([*args, "--constraints-json", str(constraints_json)])
    capsys.readouterr()

    assert code == 2


def test_window_is_never_derived_from_the_clock(
    raw_root: Path, constraints_json: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--end-day and --days are required: no wall-clock default (D-26)."""
    args = ["--symbol", SYMBOL, "--raw-root", str(raw_root)]
    code = smoke.main([*args, "--constraints-json", str(constraints_json)])
    capsys.readouterr()

    assert code == 2
