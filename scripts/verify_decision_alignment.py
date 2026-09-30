"""Phase 11 decision-alignment verification dispatcher (D-17).

Run from the repository root::

    .venv/Scripts/python scripts/verify_decision_alignment.py <mode>

Modes: protocol, params, universe, docs, glossary, reqs, decisions, all.

Read-only: never writes to the repository, reads no environment secrets and
uses no network. Prints one ``PASS <gate>`` or ``FAIL <gate> :: <detail>``
line per gate and ends with ``ALL_PASS <mode>`` (exit 0) when every gate
passed, otherwise ``FAILED <n> gate(s)`` (exit 1). An unknown or missing mode
prints a usage line to stderr and exits 2.

A module that returns fewer gates than its expected minimum adds a
``FAIL <module>-gate-count`` line, so a silently emptied gate module cannot
pass. A module that raises is reported as ``FAIL <module>-error :: <type>``
(exception type name only, never the message).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

Gate = tuple[str, bool, str]

# step label -> (module key under scripts/decision_alignment, run function name)
STEPS: dict[str, tuple[str, str]] = {
    "protocol": ("protocol", "run"),
    "params": ("params", "run"),
    "universe": ("universe", "run"),
    "ops_risk": ("ops_risk", "run"),
    "exchange": ("exchange", "run"),
    "authority": ("authority", "run"),
    "glossary": ("bookkeeping", "run_glossary"),
    "reqs": ("bookkeeping", "run_reqs"),
    "decisions": ("bookkeeping", "run_decisions"),
}

# Fixed order for the "all" mode.
MODES: dict[str, tuple[str, ...]] = {
    "protocol": ("protocol",),
    "params": ("params",),
    "universe": ("universe",),
    "docs": ("ops_risk", "exchange", "authority"),
    "glossary": ("glossary",),
    "reqs": ("reqs",),
    "decisions": ("decisions",),
}
MODES["all"] = tuple(step for mode in MODES for step in MODES[mode])

# Minimum number of gates each step must return (guards against an emptied
# module passing vacuously). Set to the counts the modules return today.
EXPECTED_MIN: dict[str, int] = {
    "protocol": 10,
    "params": 6,
    "universe": 5,
    "ops_risk": 11,
    "exchange": 9,
    "authority": 6,
    "glossary": 6,
    "reqs": 5,
    "decisions": 6,
}

USAGE = "usage: verify_decision_alignment.py <" + "|".join(MODES) + ">"


def _load(modules: Mapping[str, Any] | None, key: str) -> Any:
    if modules is not None:
        return modules[key]
    return import_module(f"scripts.decision_alignment.{key}")


def main(argv: Sequence[str] | None = None, *, modules: Mapping[str, Any] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in MODES:
        print(USAGE, file=sys.stderr)
        return 2
    mode = args[0]

    failures = 0

    def emit(name: str, ok: bool, detail: str) -> None:
        nonlocal failures
        if ok:
            print(f"PASS {name}")
        else:
            failures += 1
            print(f"FAIL {name} :: {detail}" if detail else f"FAIL {name}")

    for step in MODES[mode]:
        key, func_name = STEPS[step]
        try:
            gates = list(getattr(_load(modules, key), func_name)())
        except Exception as exc:  # noqa: BLE001 - report the type name only, never the message
            emit(f"{step}-error", False, type(exc).__name__)
            continue
        for name, ok, detail in gates:
            emit(name, bool(ok), detail)
        if len(gates) < EXPECTED_MIN[step]:
            emit(
                f"{step}-gate-count",
                False,
                f"expected at least {EXPECTED_MIN[step]} gates, got {len(gates)}",
            )

    if failures:
        print(f"FAILED {failures} gate(s)")
        return 1
    print(f"ALL_PASS {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
