"""pytest plugin loaded by test.ps1: separates collection vs execution time.

Prints one line right after collection and a phase breakdown at the end.
"""

import time

_t = {"start": time.perf_counter()}


def pytest_collection_finish(session):
    _t["collected"] = time.perf_counter()
    print(
        f"\n[timing] collection: {_t['collected'] - _t['start']:.2f}s "
        f"({len(session.items)} tests)"
    )


def pytest_terminal_summary(terminalreporter):
    end = time.perf_counter()
    collected = _t.get("collected", _t["start"])
    terminalreporter.write_sep("=", "phase timing")
    terminalreporter.write_line(f"collection : {collected - _t['start']:7.2f}s")
    terminalreporter.write_line(f"execution  : {end - collected:7.2f}s")
    terminalreporter.write_line(f"total      : {end - _t['start']:7.2f}s")
