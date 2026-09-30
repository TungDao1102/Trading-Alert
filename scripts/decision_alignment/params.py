"""Parameter-set gate module (Phase 11, plan 11-02; D036, D037, D038, D-06, F-810).

Executable checks that keep the parameter registry honest after the D036-D038
alignment: every set is pinned, the ten pre-phase files and hashes never move, the
five new sets carry the aligned facts, and the canonical cost set is identical
across them. ``run()`` returns ``(name, ok, detail)`` tuples PA-01..PA-06; every check
is also a pure function over a params root directory so tests can inject a broken copy.

Stdlib plus ``src.domain.registry`` and ``src.backtest.costs`` only.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.backtest.costs import COST_KEYS, build_cost_model
from src.domain import registry
from src.domain.registry import ParameterSetMutated, verify_parameter_set

REPO_ROOT = Path(__file__).resolve().parents[2]
PARAMS_ROOT = REPO_ROOT / "params"
PIN_PATH = REPO_ROOT / "tests" / "fixtures" / "phase4" / "parameters.json"

SetKey = tuple[str, str]

# Ten pre-phase-11 sets: loader hash at commit 679825c (PA-03).
PRE_PHASE_HASHES: dict[SetKey, str] = {
    ("breakout-retest", "baseline-v1"): (
        "4a8ee77ee99d390c1a4ccd86ee7259f86f319451de67d76732ee4cadc0cc1969"
    ),
    ("breakout-retest", "baseline-v2"): (
        "5be12f1b36b7c3e5595a93c62aec74e52ac877848bd8658ff60be2e69584ed0b"
    ),
    ("breakout-retest", "baseline-v3"): (
        "b36f095b49bc4342a212fa2a8607602b8f98f92e26d540b56c54897a8461a03e"
    ),
    ("range-mr", "baseline-v1"): (
        "060fc4470a075b97253b4cd0e787819031d019dd2b0b857aaec02e08e6066404"
    ),
    ("range-mr", "baseline-v2"): (
        "4249bf9934e1477736b3fb3008a0d962aaa1163047fed55227b37c973de3ed0f"
    ),
    ("trend-pullback", "baseline-no-trade-v1"): (
        "8f28ddc98876326b762c7ae05a749d0b0fbb4ca9d578cc817f5663bcb4f3ad0e"
    ),
    ("trend-pullback", "baseline-simple-trend-v1"): (
        "b99f1eaa6d3b8e15f210c7ed2db4eb5dd5823e59f0de3eb25afddf9bb1426a01"
    ),
    ("trend-pullback", "baseline-v1"): (
        "e1579900b1be20b8a6db76c554255cbec8125d5d317f6df7dadd5de78d2afae5"
    ),
    ("trend-pullback", "baseline-v2"): (
        "e3176f73eecf65cbcedce218f5316fef1ce9511efc38151c4e67e2ec00e45726"
    ),
    ("trend-pullback", "baseline-v3"): (
        "5205ec6a87f4665d4ae0b0ebd5f1e5fb49bbd0ea30b20842ceb4d780b4452e57"
    ),
}

# LF-normalised sha256 of the same ten files at commit 679825c (PA-02 byte lock).
PRE_PHASE_FILE_SHA256: dict[SetKey, str] = {
    ("breakout-retest", "baseline-v1"): (
        "62ecbdffd8c2a37713d0be62999312e4f8537710ba3938775bd0502408ecb0e5"
    ),
    ("breakout-retest", "baseline-v2"): (
        "c93172aaeafd1454a73c3720e071044c80f52468ff029f200a2a90bb6df66e83"
    ),
    ("breakout-retest", "baseline-v3"): (
        "d74b4b8dbafb8e27a45538a02d61d2c1f4bb9a9536474ba55bc0729af4764e85"
    ),
    ("range-mr", "baseline-v1"): (
        "f74088d324cd816482e2866551f0c48e0e19f7a3f3c82656d9449ab15664256b"
    ),
    ("range-mr", "baseline-v2"): (
        "c03e2475589207b11f5375be3b63d0852e02133bcd5615e2f7bce28cb6783efc"
    ),
    ("trend-pullback", "baseline-no-trade-v1"): (
        "3f726067edb634c3ca72dfb7cdfa2ec4fa74154de488572e35e52732c03edc93"
    ),
    ("trend-pullback", "baseline-simple-trend-v1"): (
        "6f9f89ee6310f02c7d933e63b3ce8311f5fe9e064ed59108f6c80882b06497fb"
    ),
    ("trend-pullback", "baseline-v1"): (
        "b60d7bbe586c6796676c92b7b3aec055f2661a2d13eee135b6e6874957c9cf5b"
    ),
    ("trend-pullback", "baseline-v2"): (
        "74c92d689c3e025ef18b1f05d83027d755aa92710e2aa32da1735d8088bb7b27"
    ),
    ("trend-pullback", "baseline-v3"): (
        "d397d0be5289372c80259b2194521fb9889d1fd8b2929cfa27c594a97a21cbbd"
    ),
}

NEW_SET_IDS: tuple[SetKey, ...] = (
    ("breakout-retest", "baseline-v4"),
    ("range-mr", "baseline-v4"),
    ("trend-pullback", "baseline-no-trade-v2"),
    ("trend-pullback", "baseline-simple-trend-v2"),
    ("trend-pullback", "baseline-v4"),
)

EXPECTED_NEW_VERSION = "v3.0.0"
TAKER_FEE = Decimal("0.0005")


def _set_path(root: Path, key: SetKey) -> Path:
    return root / key[0] / f"{key[1]}.toml"


def load_pins(pin_path: Path = PIN_PATH) -> dict[SetKey, str]:
    """Read the pin file into ``{(strategy_id, parameter_set_id): hash}``."""
    doc = json.loads(pin_path.read_text(encoding="utf-8"))
    entries = doc["parameter_sets"] if "parameter_sets" in doc else [doc]
    return {(e["strategy_id"], e["parameter_set_id"]): e["parameter_set_hash"] for e in entries}


def check_pins(root: Path, pins: dict[SetKey, str]) -> list[str]:
    """PA-01: every TOML under ``root`` has a pin that verifies; no orphan pin."""
    problems: list[str] = []
    seen: set[SetKey] = set()
    for path in sorted(root.rglob("*.toml")):
        key = (path.parent.name, path.stem)
        seen.add(key)
        if key not in pins:
            problems.append(f"{key[0]}/{key[1]}: no pinned hash")
            continue
        try:
            verify_parameter_set(path, pins[key])
        except (ParameterSetMutated, registry.RegistrySchemaMismatch) as exc:
            problems.append(f"{key[0]}/{key[1]}: pinned verify failed: {exc}")
        except registry.StrategyKeyOutsideRegistry as exc:
            problems.append(f"{key[0]}/{key[1]}: registry validation failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - record any load failure per file, keep scanning
            # TOML syntax errors, undecodable bytes, unsafe path segments and the like must
            # not abort the scan or be mislabelled as a pin-file problem (WR-12).
            problems.append(f"{key[0]}/{key[1]}: load failed: {type(exc).__name__}: {exc}")
    for orphan in sorted(set(pins) - seen):
        problems.append(f"{orphan[0]}/{orphan[1]}: pin without a file")
    return problems


def _lf_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def check_byte_lock(root: Path, expected: dict[SetKey, str]) -> list[str]:
    """PA-02: pre-phase files match their LF-normalised sha256 (CRLF tolerated)."""
    problems: list[str] = []
    for key, digest in sorted(expected.items()):
        path = _set_path(root, key)
        if not path.is_file():
            problems.append(f"{key[0]}/{key[1]}: file missing")
        elif _lf_sha256(path) != digest:
            problems.append(f"{key[0]}/{key[1]}: file bytes changed (byte lock)")
    return problems


def check_old_hashes(root: Path, expected: dict[SetKey, str]) -> list[str]:
    """PA-03: pre-phase parameter_set_hash values are unchanged."""
    problems: list[str] = []
    for key, digest in sorted(expected.items()):
        path = _set_path(root, key)
        if not path.is_file():
            problems.append(f"{key[0]}/{key[1]}: file missing")
            continue
        try:
            verify_parameter_set(path, digest)
        except Exception as exc:
            problems.append(f"{key[0]}/{key[1]}: hash moved: {exc}")
    return problems


def _parse(root: Path, key: SetKey) -> tuple[str, dict[str, Any]]:
    path = _set_path(root, key)
    text = path.read_bytes().decode("utf-8")
    return registry._parse_and_validate(text, path, key[0], key[1])


def check_new_set_facts(root: Path, ids: tuple[SetKey, ...]) -> list[str]:
    """PA-04: the D036-D038 facts hold in each new set and its header says Supersedes."""
    problems: list[str] = []
    for key in ids:
        label = f"{key[0]}/{key[1]}"
        path = _set_path(root, key)
        if not path.is_file():
            problems.append(f"{label}: file missing")
            continue
        try:
            version, params = _parse(root, key)
        except Exception as exc:
            problems.append(f"{label}: does not load: {exc}")
            continue
        if version != EXPECTED_NEW_VERSION:
            problems.append(f"{label}: strategy_version {version!r}, want {EXPECTED_NEW_VERSION}")
        fraction = params.get("partial_fill_fraction")
        if fraction != 1 or isinstance(fraction, bool):
            problems.append(f"{label}: partial_fill_fraction {fraction!r}, want 1 (D038)")
        if params.get("working_type") != "MARK_PRICE":
            problems.append(f"{label}: working_type {params.get('working_type')!r} (D037)")
        entry = params.get("fee_rate_entry")
        exit_ = params.get("fee_rate_exit")
        if entry != TAKER_FEE or exit_ != TAKER_FEE:
            problems.append(f"{label}: fee_rate_entry {entry!r} / fee_rate_exit {exit_!r} (D036)")
        header = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("#")]
        if not any("Supersedes" in ln for ln in header):
            problems.append(f"{label}: header comment lacks 'Supersedes'")
    return problems


def check_cost_hash_parity(root: Path, ids: tuple[SetKey, ...]) -> list[str]:
    """PA-05: all new sets share one cost_model_hash (D038 canonical cost set)."""
    hashes: dict[str, list[str]] = {}
    problems: list[str] = []
    for key in ids:
        label = f"{key[0]}/{key[1]}"
        try:
            _, params = _parse(root, key)
            model = build_cost_model({k: params[k] for k in COST_KEYS})
        except Exception as exc:
            problems.append(f"{label}: cost model not buildable: {exc}")
            continue
        hashes.setdefault(model.cost_model_hash, []).append(label)
    if len(hashes) > 1:
        problems.append(f"cost_model_hash differs across new sets: {hashes}")
    return problems


def check_working_type_registry() -> list[str]:
    """PA-06: working_type is a registry string key and not a cost key."""
    problems: list[str] = []
    if "working_type" not in registry.STRATEGY_KEYS:
        problems.append("working_type missing from STRATEGY_KEYS")
    if "working_type" not in registry.STRING_KEYS:
        problems.append("working_type missing from STRING_KEYS")
    if "working_type" in COST_KEYS:
        problems.append("working_type must not be a cost key")
    return problems


def _result(name: str, problems: list[str]) -> tuple[str, bool, str]:
    if problems:
        return (name, False, "; ".join(problems))
    return (name, True, "ok")


def run() -> list[tuple[str, bool, str]]:
    """Evaluate gates PA-01..PA-06 against the real repository."""
    try:
        pin_problems = check_pins(PARAMS_ROOT, load_pins())
    except (OSError, ValueError, KeyError) as exc:
        pin_problems = [f"pin file unreadable: {exc}"]
    return [
        _result("PA-01", pin_problems),
        _result("PA-02", check_byte_lock(PARAMS_ROOT, PRE_PHASE_FILE_SHA256)),
        _result("PA-03", check_old_hashes(PARAMS_ROOT, PRE_PHASE_HASHES)),
        _result("PA-04", check_new_set_facts(PARAMS_ROOT, NEW_SET_IDS)),
        _result("PA-05", check_cost_hash_parity(PARAMS_ROOT, NEW_SET_IDS)),
        _result("PA-06", check_working_type_registry()),
    ]


if __name__ == "__main__":
    import sys

    results = run()
    for name, ok, detail in results:
        print(f"{name} {'ok' if ok else 'FAIL'} {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
