"""The raw root is resolved once per call, not twice per file (quick task 261020-spd, B1).

`build_case_input_data` used to relate every file to the raw root twice (once for `files`, once
inside `dataset_identity`), resolving both the file and the root each time. It now resolves the
root once and relates each file once. This module keeps the old code as a reference copy and
checks that the files tuple, the dataset_id, their ordering and every error (type, message and
cause) are unchanged: on multi-symbol stores, with and without the funding, mark and trade
series, for relative, absolute, trailing-separator, backslash, dot-dot and junction or symlink
spellings of the root, and for files outside the root.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from src.data import case_input as ci
from src.domain.canonical import sha256_hex

from tests.test_case_input_builder import AS_OF, OTHER, START, SYMBOL, build_store

END = START + timedelta(days=1)


# --------------------------------------------------------------------------- #
# Reference copy of the code before the change (src/data/case_input.py at a87489b).
# --------------------------------------------------------------------------- #


def _old_relative_posix(raw_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(raw_root.resolve()).as_posix()
    except ValueError as exc:
        raise ci.CaseInputError(f"{path} is not under raw root {raw_root}") from exc


def _old_dataset_identity(raw_root: Path, files: Iterable[Path]) -> str:
    entries: dict[str, str] = {}
    for path in files:
        entries[_old_relative_posix(raw_root, path)] = ci._file_sha256(path)
    payload = {"files": [{"path": rel, "sha256": entries[rel]} for rel in sorted(entries)]}
    return sha256_hex(payload)


def _old_files_and_identity(raw_root: Path, used: Sequence[Path]) -> tuple[tuple[str, ...], str]:
    """The two tail lines of the old `build_case_input_data`."""
    relative = tuple(sorted({_old_relative_posix(raw_root, p) for p in used}))
    return relative, _old_dataset_identity(raw_root, used)


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def _outcome(call: Any) -> tuple[str, Any]:
    """('ok', value) or ('error', (type, message, cause type)) of `call()`."""
    try:
        return "ok", call()
    except Exception as exc:  # noqa: BLE001 - the exception itself is the compared value
        cause = type(exc.__cause__).__name__ if exc.__cause__ is not None else None
        return "error", (type(exc).__name__, str(exc), cause)


def _same(old: Any, new: Any) -> tuple[str, Any]:
    expected = _outcome(old)
    actual = _outcome(new)
    assert actual == expected
    return expected


@pytest.fixture(scope="module")
def stores(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """A full two-symbol store, and copies without funding, without mark and without 4h bars."""
    base = tmp_path_factory.mktemp("relative_paths")
    full = base / "full" / "raw"
    build_store(full, start=START, end=END, symbols=(SYMBOL, OTHER))
    out = {"full": full}
    for name, drop in (
        ("no_funding", Path("data_class=funding")),
        ("no_mark", Path("dataset=mark_klines")),
        ("no_4h", Path("interval=4h")),
    ):
        copy = base / name / "raw"
        shutil.copytree(full, copy)
        shutil.rmtree(copy / drop)
        out[name] = copy
    return out


def _all_files(root: Path) -> list[Path]:
    """Every published file except the open-interest ticks, plus 12 of those (time bound)."""
    files = sorted(p for p in root.rglob("*.parquet") if p.is_file())
    oi = [p for p in files if "data_class=oi" in p.as_posix()]
    rest = [p for p in files if "data_class=oi" not in p.as_posix()]
    return rest + oi[:: max(1, len(oi) // 12)][:12]


# (store, series): every series choice that the store can build. The full store covers the
# engine series, every series (open interest included) and single series; each copy covers a
# choice without the series it lacks.
CASES: list[tuple[str, tuple[str, ...]]] = [
    ("full", ci.ENGINE_SERIES),
    ("full", ci.SERIES_ALL),
    ("full", ("trade",)),
    ("full", ("trade", "funding")),
    ("full", ("mark_1m",)),
    ("full", ("funding", "open_interest")),
    ("no_funding", ("trade", "intrabar_1m", "mark_1m")),
    ("no_mark", ("trade", "funding")),
    ("no_4h", ("intrabar_1m", "mark_1m", "funding")),
]


# --------------------------------------------------------------------------- #
# The whole builder output, new code against the old tail.
# --------------------------------------------------------------------------- #


def _build(raw_root: Path, series: tuple[str, ...], **extra: Any) -> ci.CaseInputData:
    return ci.build_case_input_data(
        raw_root,
        symbols=[OTHER, SYMBOL],
        start_utc=START,
        end_utc=END,
        as_of_day_utc=AS_OF,
        series=series,
        **extra,
    )


@pytest.mark.parametrize(
    ("store", "series"), CASES, ids=[f"{name}-{'+'.join(series)}" for name, series in CASES]
)
def test_the_builder_output_is_the_output_of_the_old_code(
    stores: dict[str, Path],
    store: str,
    series: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = stores[store]
    new = _build(root, series)
    with monkeypatch.context() as patch:
        patch.setattr(ci, "_files_and_identity", _old_files_and_identity)
        old = _build(root, series)
    assert new == old
    assert repr(new) == repr(old)
    assert new.files == tuple(sorted(new.files))
    assert all("\\" not in f and not f.startswith("/") for f in new.files)


def test_the_builder_with_minute_rows_matches_the_old_code(
    stores: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    new = _build(stores["full"], ci.ENGINE_SERIES, with_minute_rows=True)
    with monkeypatch.context() as patch:
        patch.setattr(ci, "_files_and_identity", _old_files_and_identity)
        old = _build(stores["full"], ci.ENGINE_SERIES, with_minute_rows=True)
    assert new == old
    assert repr(new) == repr(old)


# --------------------------------------------------------------------------- #
# The helpers on spelled roots, file orders, duplicates and outside files.
# --------------------------------------------------------------------------- #


def _spellings(root: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """The root as absolute, relative to the cwd, with a trailing separator, with backslashes,
    with forward slashes and through a `..` segment."""
    monkeypatch.chdir(root.parent.parent)
    relative = Path(root.parent.name) / root.name
    text = str(root)
    return [
        root,
        relative,
        Path(text + os.sep),
        Path(text.replace("/", "\\")),
        Path(text.replace("\\", "/")),
        root.parent / ".." / root.parent.name / root.name,
    ]


def _file_lists(root: Path, spelled: Path) -> list[list[Path]]:
    """Files named through the spelled root and through the plain root, in several orders."""
    absolute = _all_files(root)
    spelled_files = [spelled / p.relative_to(root) for p in absolute]
    sample = absolute[:: max(1, len(absolute) // 40)]
    return [
        absolute,
        list(reversed(absolute)),
        spelled_files,
        sample + sample,  # duplicates
        [spelled / p.relative_to(root) for p in reversed(sample)],
        [],
    ]


def test_spelled_roots_give_the_same_files_and_identity(
    stores: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    compared = 0
    for name in ("full", "no_mark"):
        root = stores[name]
        for spelled in _spellings(root, monkeypatch):
            for files in _file_lists(root, spelled):
                kind, _ = _same(
                    lambda s=spelled, f=files: _old_files_and_identity(s, f),
                    lambda s=spelled, f=files: ci._files_and_identity(s, f),
                )
                assert kind == "ok"
                _same(
                    lambda s=spelled, f=files: _old_dataset_identity(s, f),
                    lambda s=spelled, f=files: ci.dataset_identity(s, f),
                )
                compared += 1
    assert compared == 2 * 6 * 6


def _link_root(target: Path, link: Path) -> bool:
    """Create `link` pointing at `target` (a symlink, else a Windows junction)."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # type: ignore[attr-defined]
        return True
    except (ImportError, AttributeError, OSError):
        return False


def test_a_root_through_a_link_gives_the_same_files_and_identity(
    stores: dict[str, Path], tmp_path: Path
) -> None:
    root = stores["full"]
    link = tmp_path / "linked_raw"
    if not _link_root(root, link):
        pytest.skip("neither a symlink nor a junction can be created here")
    files_via_link = [link / p.relative_to(root) for p in _all_files(root)]
    files_direct = _all_files(root)
    for spelled_root in (link, root):
        for files in (files_via_link, files_direct, files_via_link[:7] + files_direct[-7:]):
            kind, value = _same(
                lambda r=spelled_root, f=files: _old_files_and_identity(r, f),
                lambda r=spelled_root, f=files: ci._files_and_identity(r, f),
            )
            assert kind == "ok"
            _same(
                lambda r=spelled_root, f=files: _old_dataset_identity(r, f),
                lambda r=spelled_root, f=files: ci.dataset_identity(r, f),
            )
    # The builder through the link equals the builder through the real root, old and new.
    assert _build(link, ci.ENGINE_SERIES) == _build(root, ci.ENGINE_SERIES)


def test_files_outside_the_root_raise_the_same_error(
    stores: dict[str, Path], tmp_path: Path
) -> None:
    root = stores["full"]
    inside = _all_files(root)
    outside_file = tmp_path / "elsewhere" / "x.parquet"
    outside_file.parent.mkdir()
    outside_file.write_bytes(inside[0].read_bytes())
    sibling = root.parent / "raw2" / "y.parquet"  # a root-prefixed name that is not under it
    missing_inside = root / "interval=1h" / "missing.parquet"
    lists: list[list[Path]] = [
        [outside_file],
        inside[:3] + [outside_file],
        [outside_file] + inside[:3],
        inside[:2] + [sibling],
        [missing_inside, outside_file],  # identity: sha256 error first; files: path error first
        [outside_file, missing_inside],
        [sibling],  # outside AND unreadable: the identity hashes a file before relating it
        inside[:2] + [missing_inside],
        [root.parent / "raw" / ".." / "elsewhere.parquet"],
    ]
    errors = 0
    for files in lists:
        for spelled in (root, Path(str(root) + os.sep)):
            kind, _ = _same(
                lambda r=spelled, f=files: _old_files_and_identity(r, f),
                lambda r=spelled, f=files: ci._files_and_identity(r, f),
            )
            errors += kind == "error"
            kind, _ = _same(
                lambda r=spelled, f=files: _old_dataset_identity(r, f),
                lambda r=spelled, f=files: ci.dataset_identity(r, f),
            )
            errors += kind == "error"
    assert errors == len(lists) * 2 * 2


def test_a_root_that_cannot_be_resolved_fails_the_same_way(stores: dict[str, Path]) -> None:
    """A root with a NUL character: no error for no files, the same error for any file."""
    bad_root = Path(str(stores["full"]) + "\x00bad")
    files = _all_files(stores["full"])[:3]
    for listing in ([], files):
        _same(
            lambda f=listing: _old_files_and_identity(bad_root, f),
            lambda f=listing: ci._files_and_identity(bad_root, f),
        )
        _same(
            lambda f=listing: _old_dataset_identity(bad_root, f),
            lambda f=listing: ci.dataset_identity(bad_root, f),
        )
