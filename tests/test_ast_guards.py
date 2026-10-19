"""Negative controls for the shared AST guards of `tests/support/ast_guards.py` (review WR-07).

A purity guard that silently stopped matching would leave every module test green, so each
spelling of a clock read the guard claims to see has a seeded snippet here. The snippets are
parsed, never imported or run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.ast_guards import wall_clock_calls


def _calls(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    path = tmp_path / "seeded.py"
    path.write_text(source, encoding="utf-8")
    return wall_clock_calls(path)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import time\nx = time.time()\n", "time.time"),
        ("import time as t\nx = t.time()\n", "time.time"),
        ("import time as t\nx = t.monotonic_ns()\n", "time.monotonic_ns"),
        ("from time import monotonic as mono\nx = mono()\n", "time.monotonic"),
        ("from datetime import datetime\nx = datetime.now()\n", "datetime.now"),
        ("from datetime import datetime as DT\nx = DT.now()\n", "datetime.datetime.now"),
        ("from datetime import date as D\nx = D.today()\n", "datetime.date.today"),
        ("import datetime as dt\nx = dt.datetime.utcnow()\n", "dt.datetime.utcnow"),
        (
            "import asyncio\nx = asyncio.get_running_loop().time()\n",
            "asyncio.get_running_loop().time",
        ),
        ("import asyncio\nx = asyncio.get_event_loop().time()\n", "asyncio.get_event_loop().time"),
        ("def f(loop):\n    return loop.time()\n", "loop.time"),
        ("class A:\n    def f(self):\n        return self.loop.time()\n", "self.loop.time"),
    ],
)
def test_every_spelling_of_a_clock_read_is_found(
    tmp_path: Path, source: str, expected: str
) -> None:
    assert [name for _, name in _calls(tmp_path, source)] == [expected]


@pytest.mark.parametrize(
    "source",
    [
        "import time as t\nx = t.sleep\n",
        "from datetime import timedelta as TD\nx = TD(seconds=1)\n",
        "import datetime as dt\nx = dt.datetime(2026, 1, 1)\n",
        "def f(clock):\n    return clock()\n",
        "def f(sleep):\n    return sleep.time\n",
    ],
)
def test_reads_that_are_not_clock_calls_are_allowed(tmp_path: Path, source: str) -> None:
    assert _calls(tmp_path, source) == []
