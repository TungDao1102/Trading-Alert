"""Retention 7 daily / 4 weekly / 6 monthly for remote snapshots (Phase 13.1 plan 08, D-12 / D-17).

``select_retained`` is a pure function over snapshot names. The 400-day test drives snapshot
creation with an injected clock, applies retention after every step and compares the survivors to
an independent brute-force oracle written differently from the implementation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from src.ops import backup_remote as remote
from src.ops.backup_remote import RcloneResult, RemoteError, select_retained, snapshot_id

SENTINEL_ARG = "BACKUPS3CRYPT:_sentinel/sentinel.txt"


def _name(year: int, month: int, day: int, hour: int = 3, minute: int = 15) -> str:
    return snapshot_id(datetime(year, month, day, hour, minute, 0, tzinfo=UTC))


# --------------------------------------------------------------------------- #
# Pure function behaviour
# --------------------------------------------------------------------------- #


def test_empty_input_returns_two_empty_sets() -> None:
    assert select_retained([]) == (frozenset(), frozenset())


def test_single_name_is_kept() -> None:
    name = _name(2026, 10, 1)
    assert select_retained([name]) == (frozenset({name}), frozenset())


def test_unparseable_names_are_in_neither_set() -> None:
    good = _name(2026, 10, 1)
    keep, delete = select_retained([good, "latest", "tmp", "20261001", "20261301T000000Z"])

    assert keep == {good}
    assert delete == frozenset()


def test_only_unparseable_names_means_nothing_kept_or_deleted() -> None:
    assert select_retained(["a", "b"]) == (frozenset(), frozenset())


def test_two_snapshots_on_one_day_only_the_later_counts_for_that_day() -> None:
    early = _name(2026, 10, 1, 1, 0)
    late = _name(2026, 10, 1, 23, 0)

    keep, delete = select_retained([early, late], keep_weekly=0, keep_monthly=0)

    assert keep == {late}
    assert delete == {early}


def test_newest_overall_is_kept_even_with_all_windows_zero() -> None:
    old = _name(2026, 1, 1)
    new = _name(2026, 10, 1)

    keep, delete = select_retained([old, new], keep_daily=0, keep_weekly=0, keep_monthly=0)

    assert keep == {new}
    assert delete == {old}


def test_duplicate_names_are_treated_as_one() -> None:
    name = _name(2026, 10, 1)
    assert select_retained([name, name]) == (frozenset({name}), frozenset())


def test_fewer_periods_than_the_window_keeps_every_period() -> None:
    names = _daily_names(5)  # 5 days in one week and one month, window sizes 7/4/6

    assert select_retained(names) == (frozenset(names), frozenset())


def test_weekly_and_monthly_windows_keep_older_representatives() -> None:
    # One snapshot per day for 70 days: 7 daily + weekly/monthly picks, everything else goes.
    start = datetime(2026, 1, 1, 3, 15, tzinfo=UTC)
    names = [snapshot_id(start + timedelta(days=i)) for i in range(70)]

    keep, delete = select_retained(names)

    assert len(keep) <= 7 + 4 + 6
    assert keep == _oracle(names)
    assert keep | delete == set(names)
    assert not keep & delete
    assert names[-1] in keep


# --------------------------------------------------------------------------- #
# Independent oracle (brute force, written differently from the implementation)
# --------------------------------------------------------------------------- #


def _oracle(
    names: Sequence[str], *, daily: int = 7, weekly: int = 4, monthly: int = 6
) -> frozenset[str]:
    """Keep a snapshot when, for some granularity, it is the newest of its period and the
    period is among the N most recent periods that contain a snapshot.

    "Among the N most recent" is computed by counting strictly newer periods, with no sorting
    of period keys.
    """
    stamps: dict[str, datetime] = {}
    for name in names:
        parsed = remote.parse_snapshot_id(name)
        if parsed is not None:
            stamps[name] = parsed
    if not stamps:
        return frozenset()

    def day(dt: datetime) -> tuple[int, int, int]:
        return (dt.year, dt.month, dt.day)

    def week(dt: datetime) -> tuple[int, int]:
        iso = dt.isocalendar()
        return (iso.year, iso.week)

    def month(dt: datetime) -> tuple[int, int]:
        return (dt.year, dt.month)

    kept: set[str] = set()
    for period_of, limit in ((day, daily), (week, weekly), (month, monthly)):
        for name, stamp in stamps.items():
            mine = period_of(stamp)
            newest_in_period = all(
                other <= stamp for n, other in stamps.items() if period_of(other) == mine
            )
            newer_periods = {
                period_of(other) for other in stamps.values() if period_of(other) > mine
            }
            if newest_in_period and len(newer_periods) < limit:
                kept.add(name)
    newest = max(stamps, key=lambda n: stamps[n])
    kept.add(newest)
    return frozenset(kept)


def test_oracle_agrees_with_the_documented_example() -> None:
    # Three snapshots in three different months: all kept by the monthly window.
    names = [_name(2026, 7, 31), _name(2026, 8, 31), _name(2026, 9, 30)]
    assert _oracle(names) == set(names)
    assert select_retained(names)[0] == set(names)


# --------------------------------------------------------------------------- #
# 400-day fake clock simulation
# --------------------------------------------------------------------------- #

HORIZON_DAYS = 400
OUTAGE_START = 150
OUTAGE_END = 180  # 30 days without any snapshot, retention still runs daily


def _simulated_runs() -> list[tuple[int, datetime]]:
    """(day index, instant) for every backup run over the horizon, in time order.

    Starts mid-2025 so the horizon crosses a year boundary at a month end (Dec 31 -> Jan 1).
    Every 10th day has two runs; days OUTAGE_START..OUTAGE_END-1 have none.
    """
    start = datetime(2025, 6, 1, 3, 15, 0, tzinfo=UTC)
    runs: list[tuple[int, datetime]] = []
    for day in range(HORIZON_DAYS):
        if OUTAGE_START <= day < OUTAGE_END:
            continue
        base = start + timedelta(days=day)
        runs.append((day, base))
        if day % 10 == 0:
            runs.append((day, base + timedelta(hours=9, minutes=7)))
    return runs


def test_fake_clock_400_days_matches_oracle_and_survives_a_30_day_outage() -> None:
    survivors: set[str] = set()
    runs_by_day: dict[int, list[datetime]] = {}
    for day, instant in _simulated_runs():
        runs_by_day.setdefault(day, []).append(instant)

    pre_outage_daily: list[str] = []
    year_boundary_seen = False
    start = datetime(2025, 6, 1, 3, 15, 0, tzinfo=UTC)

    for day in range(HORIZON_DAYS):
        today = start + timedelta(days=day)
        if today.month == 1 and today.day == 1:
            year_boundary_seen = True
        for instant in runs_by_day.get(day, []):
            survivors.add(snapshot_id(instant))
            keep, delete = select_retained(survivors)
            assert keep == _oracle(sorted(survivors))
            survivors = set(keep)
            assert delete.isdisjoint(survivors)
            assert max(survivors) == snapshot_id(instant)  # the newest is always kept
            assert len(survivors) <= 7 + 4 + 6
        if not runs_by_day.get(day):
            # An outage day: the retention job still runs; nothing new has appeared.
            keep, _ = select_retained(survivors)
            assert keep == _oracle(sorted(survivors))
            survivors = set(keep)
        if day == OUTAGE_START - 1:
            pre_outage_daily = _newest_per_day(survivors)[-7:]
        if OUTAGE_START <= day < OUTAGE_END:
            # Retention during an outage never ages out the last good daily snapshots.
            assert set(pre_outage_daily) <= survivors

    assert year_boundary_seen
    assert len(pre_outage_daily) == 7
    # The very first run after the outage: the 6 newest pre-outage days remain beside it.
    after = sorted(survivors)
    assert after[-1] == snapshot_id(runs_by_day[HORIZON_DAYS - 1][-1])


def test_after_the_outage_the_first_new_run_still_leaves_six_pre_outage_days() -> None:
    start = datetime(2025, 6, 1, 3, 15, 0, tzinfo=UTC)
    survivors: set[str] = set()
    for day in range(OUTAGE_START):
        survivors.add(snapshot_id(start + timedelta(days=day)))
        survivors = set(select_retained(survivors)[0])
    pre_outage_daily = _newest_per_day(survivors)[-7:]
    assert len(pre_outage_daily) == 7

    survivors.add(snapshot_id(start + timedelta(days=OUTAGE_END)))
    survivors = set(select_retained(survivors)[0])

    assert set(pre_outage_daily[1:]) <= survivors  # 1 new daily + the 6 newest older days


def _newest_per_day(names: set[str]) -> list[str]:
    best: dict[str, str] = {}
    for name in sorted(names):
        best[name[:8]] = name
    return [best[d] for d in sorted(best)]


# --------------------------------------------------------------------------- #
# apply_retention with a fake runner
# --------------------------------------------------------------------------- #


class FakeRemote:
    """A fake rclone with a sentinel and a fixed snapshots listing; records every argv."""

    def __init__(
        self,
        listing: list[str],
        *,
        sentinel: RcloneResult | None = None,
        listing_code: int = 0,
        complete: list[str] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.listing = listing
        self.complete = complete  # ids that have a manifest; None means every listed id
        self.listing_code = listing_code
        self.sentinel = sentinel or RcloneResult(0, remote.SENTINEL_CONTENT, "")

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
        self.calls.append(list(argv))
        if list(argv)[:2] == ["cat", SENTINEL_ARG]:
            return self.sentinel
        if argv[0] == "lsf" and "-R" in argv:  # recursive listing of every snapshot's files
            names = self.listing if self.complete is None else self.complete
            stdout = "".join(
                f"{name}/{leaf}\n" for name in names for leaf in ("manifest.json", "pg.dump")
            )
            return RcloneResult(self.listing_code, stdout, "")
        if argv[0] == "lsf":
            stdout = "".join(f"{name}/\n" for name in self.listing)
            return RcloneResult(self.listing_code, stdout, "")
        return RcloneResult(0, "", "")

    def purged(self) -> list[str]:
        return [call[1] for call in self.calls if call[0] == "purge"]


def _daily_names(count: int) -> list[str]:
    start = datetime(2026, 1, 1, 3, 15, tzinfo=UTC)
    return [snapshot_id(start + timedelta(days=i)) for i in range(count)]


def test_apply_retention_checks_sentinel_lists_then_purges_exactly_the_delete_set() -> None:
    names = _daily_names(40)
    fake = FakeRemote(names + ["notes"])
    keep, delete = select_retained(names)

    report = remote.apply_retention(fake, dry_run=False)

    assert fake.calls[0] == ["cat", SENTINEL_ARG]
    assert fake.calls[1] == ["lsf", "--dirs-only", "BACKUPS3CRYPT:snapshots/"]
    assert set(fake.purged()) == {f"BACKUPS3CRYPT:snapshots/{n}" for n in delete}
    assert "BACKUPS3CRYPT:snapshots/notes" not in fake.purged()
    assert fake.calls[2] == [
        "lsf",
        "--files-only",
        "-R",
        "--max-depth",
        "2",
        "BACKUPS3CRYPT:snapshots/",
    ]
    assert all(
        arg.startswith("BACKUPS3CRYPT:snapshots/") for call in fake.calls[3:] for arg in call[1:]
    )
    assert set(report.kept) == keep
    assert set(report.deleted) == delete
    assert not report.dry_run


def test_apply_retention_ignores_an_incomplete_snapshot_when_choosing_what_to_keep() -> None:
    names = _daily_names(40)
    # Later than the newest complete snapshot (a push that may still be running): left alone.
    incomplete = snapshot_id(datetime(2026, 2, 20, 23, 0, tzinfo=UTC))
    fake = FakeRemote([*names, incomplete], complete=names)

    report = remote.apply_retention(fake, dry_run=True)

    keep, delete = select_retained(names)
    assert set(report.kept) == keep
    assert incomplete not in report.kept
    assert incomplete not in report.deleted
    assert set(report.deleted) == delete


def test_apply_retention_purges_an_incomplete_snapshot_older_than_the_newest_complete() -> None:
    names = _daily_names(40)
    incomplete = snapshot_id(datetime(2026, 1, 5, 23, 0, tzinfo=UTC))
    fake = FakeRemote([*names, incomplete], complete=names)

    report = remote.apply_retention(fake, dry_run=False)

    assert incomplete in report.deleted
    assert f"BACKUPS3CRYPT:snapshots/{incomplete}" in fake.purged()


def test_apply_retention_never_touches_parquet_and_never_uses_sync_or_move() -> None:
    fake = FakeRemote(_daily_names(40))

    remote.apply_retention(fake, dry_run=False)

    flat = [arg for call in fake.calls for arg in call]
    assert not any("parquet" in arg for arg in flat)
    assert {call[0] for call in fake.calls} <= {"cat", "lsf", "purge"}


def test_apply_retention_dry_run_lists_without_purging() -> None:
    fake = FakeRemote(_daily_names(40))

    report = remote.apply_retention(fake, dry_run=True)

    assert fake.purged() == []
    assert report.deleted
    assert report.dry_run


@pytest.mark.parametrize("code", [0, 3])
def test_apply_retention_empty_listing_is_an_error_not_nothing_to_do(code: int) -> None:
    fake = FakeRemote([], listing_code=code)

    with pytest.raises(RemoteError, match="no snapshots"):
        remote.apply_retention(fake, dry_run=False)

    assert fake.purged() == []


def test_apply_retention_refuses_when_the_sentinel_check_fails() -> None:
    fake = FakeRemote(_daily_names(40), sentinel=RcloneResult(3, "", "directory not found"))

    with pytest.raises(RemoteError, match="sentinel"):
        remote.apply_retention(fake, dry_run=False)

    assert fake.calls == [["cat", SENTINEL_ARG]]


def test_apply_retention_stops_on_a_failed_purge() -> None:
    class FailingPurge(FakeRemote):
        def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> RcloneResult:
            if argv[0] == "purge":
                self.calls.append(list(argv))
                return RcloneResult(1, "", "boom")
            return super().__call__(argv, env)

    fake = FailingPurge(_daily_names(40))

    with pytest.raises(RemoteError, match="purge failed"):
        remote.apply_retention(fake, dry_run=False)

    assert len(fake.purged()) == 1


def test_retain_cli_prints_counts_and_supports_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from src.ops.backup import main

    names = _daily_names(40)
    fake = FakeRemote(names)

    assert main(["retain", "--dry-run"], rclone_runner=fake) == 0
    out = capsys.readouterr().out
    assert "retain-OK dry_run=True" in out
    assert fake.purged() == []

    assert main(["retain"], rclone_runner=fake) == 0
    assert "retain-OK dry_run=False" in capsys.readouterr().out
    assert fake.purged()
