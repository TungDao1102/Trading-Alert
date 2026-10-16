"""In-image load check of the paper runtime's start inputs (plan 16-55 Task 1, review B2-CR-05).

`deploy/soak-image.sh` runs this inside the freshly built runtime image, with no network:

    docker run --rm --network none --env PAPER_RUNTIME_CONFIG=<in-image path> \
        --entrypoint /app/.venv/bin/python trading-alert:<commit> \
        -m scripts.check_image_paths --root /app

It answers one question: can the image admit and configure its paper runtime? It loads every
allowlisted parameter set from `<root>/params` (the allowlist is read through the freeze accessor
only) and checks that the set's hash is the hash its allowlist entry approves, then loads the
runtime configuration file named by `PAPER_RUNTIME_CONFIG` with the runtime's own loader. It opens
no database, no network connection and no Telegram client.

Output names only: the set ids, the configuration path and the names of missing or invalid keys.
No value of the parameter set, the configuration or the environment is ever printed.

Exit codes: 0 every check passed (an empty allowlist passes and says so); 1 a set or the
configuration cannot be loaded in this tree (each failure is named on stderr); 2 usage.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from src.paper.freeze import allowlist_entries, load_parameter_set_at_root
from src.paper.runtime_config import CONFIG_VARIABLE, ConfigNotRatified, load_runtime_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.check_image_paths",
        description="Check that the allowlisted parameter sets and the runtime configuration load.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Application root that holds params/ (in the image: /app).",
    )
    return parser


def _check_sets(root: Path) -> list[str]:
    """One failure line per allowlisted set that does not load or whose hash differs."""
    failures: list[str] = []
    entries = allowlist_entries()
    if not entries:
        print("parameter sets: nothing is allowlisted, no set to check")
        return failures
    registry = root / "params"
    for entry in entries:
        label = f"{entry.strategy_id}/{entry.parameter_set_id}"
        try:
            loaded = load_parameter_set_at_root(entry.strategy_id, entry.parameter_set_id, registry)
        except Exception as exc:  # any defect of the file or its absence, named by type only
            failures.append(f"parameter set {label}: cannot be loaded ({type(exc).__name__})")
            continue
        if loaded.parameter_set_hash != entry.parameter_set_hash:
            failures.append(
                f"parameter set {label}: its hash is not the hash the allowlist entry approves"
            )
            continue
        print(f"parameter set {label}: loaded, hash matches the allowlist entry")
    return failures


def _check_config(root: Path, environ: Mapping[str, str]) -> list[str]:
    """The runtime configuration named by PAPER_RUNTIME_CONFIG, loaded by the runtime loader."""
    raw = environ.get(CONFIG_VARIABLE)
    if raw is None or raw.strip() == "":
        return [f"{CONFIG_VARIABLE} is not set: no runtime configuration to check"]
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        load_runtime_config(str(path))
    except ConfigNotRatified as exc:
        # The problems name the variable or `<section>.<key>`, never a value of the file.
        return [f"runtime configuration {path.as_posix()} ({CONFIG_VARIABLE}): {exc}"]
    print(f"runtime configuration {path.as_posix()}: loaded")
    return []


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    env: Mapping[str, str] = os.environ if environ is None else environ
    root: Path = args.root
    failures = [*_check_sets(root), *_check_config(root, env)]
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    if failures:
        print("in-image check failed", file=sys.stderr)
        return 1
    print("in-image check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
