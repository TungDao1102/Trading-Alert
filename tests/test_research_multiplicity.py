"""Quick 261014-cvk Task 2: the Holm step-down that executes decision D069 (protocol v2.3.0).

One Holm-Bonferroni procedure at family-wise alpha = 0.05 over the 48 candidate-level one-sided
p-values of the three registered grids (16 per family). The module only corrects p-values it is
given; the p-value producer does not exist yet. No Holdout, no ExperimentRecord, no market data.
"""

from __future__ import annotations

import inspect
import json
import math
import random
from pathlib import Path

import pytest
from src.research import multiplicity
from src.research.manifest import ManifestError
from src.research.multiplicity import (
    EXPECTED_HYPOTHESES,
    FAMILY_WISE_ALPHA,
    MultiplicityError,
    confirmatory_hypothesis_ids,
    g3_passes,
    holm_adjust,
    holm_adjust_confirmatory,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PREREG_DIR = REPO_ROOT / "docs" / "research" / "preregistration"


def _canonical(adjusted: dict[str, float]) -> str:
    return json.dumps(adjusted, sort_keys=False)


def test_textbook_holm_step_down() -> None:
    p = {"h1": 0.01, "h2": 0.04, "h3": 0.03, "h4": 0.005}
    adjusted = holm_adjust(p)
    # Sorted derivation (m = 4): 0.005*4 = 0.02, 0.01*3 = 0.03, 0.03*2 = 0.06,
    # max(0.04*1, 0.06) = 0.06 (the running maximum makes it non-decreasing).
    expected = {"h1": 0.03, "h2": 0.06, "h3": 0.06, "h4": 0.02}
    assert set(adjusted) == set(expected)
    for key, value in expected.items():
        assert adjusted[key] == pytest.approx(value, abs=1e-12)
    ordered = sorted(p, key=lambda k: (p[k], k))
    values = [adjusted[k] for k in ordered]
    assert values == sorted(values)
    assert all(0.0 <= v <= 1.0 for v in values)


def test_adjusted_values_are_capped_at_one() -> None:
    adjusted = holm_adjust({"a": 0.6, "b": 0.7, "c": 0.9})
    assert adjusted == {"a": 1.0, "b": 1.0, "c": 1.0}


def test_order_independence_and_ties() -> None:
    p = {"h1": 0.01, "h2": 0.01, "h3": 0.2, "h4": 0.01, "h5": 0.5}
    base = holm_adjust(p)
    keys = list(p)
    for seed in range(5):
        shuffled = keys[:]
        random.Random(seed).shuffle(shuffled)
        again = holm_adjust({k: p[k] for k in shuffled})
        assert _canonical(again) == _canonical(base)
    assert base["h1"] == base["h2"] == base["h4"]
    # three tied p = 0.01 over m = 5: the first of the tie carries 5*0.01 and the running
    # maximum gives the whole tie group that value.
    assert base["h1"] == pytest.approx(0.05, abs=1e-12)


def test_global_is_never_smaller_than_per_family() -> None:
    rng = random.Random(20261014)
    ids = confirmatory_hypothesis_ids()
    p = {hid: rng.random() ** 3 for hid in ids}
    global_adj = holm_adjust(p)
    by_family: dict[str, dict[str, float]] = {}
    for hid, value in p.items():
        by_family.setdefault(hid.split("/", 1)[0], {})[hid] = value
    assert sorted(len(v) for v in by_family.values()) == [16, 16, 16]
    for family_p in by_family.values():
        per_family = holm_adjust(family_p)
        for hid, value in per_family.items():
            assert global_adj[hid] >= value


def test_confirmatory_hypothesis_ids_match_the_three_registered_grids() -> None:
    ids = confirmatory_hypothesis_ids()
    assert len(ids) == EXPECTED_HYPOTHESES == 48
    assert len(set(ids)) == 48
    families: dict[str, int] = {}
    for hid in ids:
        strategy_id, parameter_set_id = hid.split("/", 1)
        assert parameter_set_id.startswith("research-run-1-")
        families[strategy_id] = families.get(strategy_id, 0) + 1
    assert families == {"breakout-retest": 16, "range-mr": 16, "trend-pullback": 16}
    assert ids == tuple(sorted(ids))


def _write_grid(directory: Path, name: str, strategy_id: str, count: int) -> None:
    points = [
        {
            "parameter_set_id": f"research-run-1-{name}{i:02d}",
            "parameter_set_hash": f"{i:064x}",
            "varied": [["k", str(i)]],
        }
        for i in range(1, count + 1)
    ]
    path = directory / f"research-run-1-grid-{name}.json"
    path.write_text(json.dumps({"strategy_id": strategy_id, "points": points}), encoding="utf-8")


def test_confirmatory_ids_refuse_any_other_count(tmp_path: Path) -> None:
    _write_grid(tmp_path, "a", "sa", 16)
    _write_grid(tmp_path, "b", "sb", 16)
    with pytest.raises(MultiplicityError):  # only two grid files
        confirmatory_hypothesis_ids(tmp_path)
    _write_grid(tmp_path, "c", "sc", 15)
    with pytest.raises(MultiplicityError):  # 47 hypotheses
        confirmatory_hypothesis_ids(tmp_path)
    _write_grid(tmp_path, "c", "sc", 16)
    assert len(confirmatory_hypothesis_ids(tmp_path)) == 48
    _write_grid(tmp_path, "d", "sd", 16)
    with pytest.raises(MultiplicityError):  # four grid files
        confirmatory_hypothesis_ids(tmp_path)
    (tmp_path / "research-run-1-grid-d.json").unlink()
    _write_grid(tmp_path, "c", "sa", 16)
    with pytest.raises(MultiplicityError):  # two files share a strategy_id
        confirmatory_hypothesis_ids(tmp_path)


def test_multiplicity_error_is_a_manifest_error() -> None:
    assert issubclass(MultiplicityError, ManifestError)


def _full_valid() -> dict[str, float]:
    return {hid: 0.5 for hid in confirmatory_hypothesis_ids()}


def test_confirmatory_adjustment_accepts_exactly_the_48_ids() -> None:
    out = holm_adjust_confirmatory(_full_valid())
    assert len(out) == 48
    assert set(out) == set(confirmatory_hypothesis_ids())
    assert all(v == 1.0 for v in out.values())


def test_confirmatory_adjustment_refuses_a_malformed_set() -> None:
    ids = confirmatory_hypothesis_ids()
    missing = _full_valid()
    del missing[ids[0]]
    with pytest.raises(MultiplicityError):
        holm_adjust_confirmatory(missing)

    extra = _full_valid()
    extra["trend-pullback/research-run-1-zzz"] = 0.1
    with pytest.raises(MultiplicityError):
        holm_adjust_confirmatory(extra)

    unknown = _full_valid()
    del unknown[ids[0]]
    unknown["trend-pullback/research-run-1-zzz"] = 0.1
    with pytest.raises(MultiplicityError):  # 48 entries, one unknown id
        holm_adjust_confirmatory(unknown)

    duplicate = _full_valid()
    duplicate[" " + ids[0]] = 0.2  # duplicate once whitespace is normalized
    del duplicate[ids[1]]
    with pytest.raises(MultiplicityError):
        holm_adjust_confirmatory(duplicate)

    with pytest.raises(MultiplicityError):
        holm_adjust_confirmatory({})


@pytest.mark.parametrize(
    "bad", [-0.1, 1.0000001, math.nan, math.inf, 1, 0, True, "0.1", None, Ellipsis]
)
def test_confirmatory_adjustment_refuses_a_bad_p_value(bad: object) -> None:
    ids = confirmatory_hypothesis_ids()
    payload: dict[str, object] = dict(_full_valid())
    payload[ids[5]] = bad
    with pytest.raises(MultiplicityError):
        holm_adjust_confirmatory(payload)  # type: ignore[arg-type]


def test_holm_adjust_refuses_an_empty_set() -> None:
    with pytest.raises(MultiplicityError):
        holm_adjust({})


def test_g3_passes_only_strictly_below_alpha() -> None:
    assert FAMILY_WISE_ALPHA == 0.05
    assert g3_passes(0.0499999) is True
    assert g3_passes(0.0) is True
    assert g3_passes(0.05) is False
    assert g3_passes(0.5) is False
    with pytest.raises(MultiplicityError):
        g3_passes(math.nan)
    with pytest.raises(MultiplicityError):
        g3_passes(1.5)


def test_seeded_monte_carlo_family_wise_false_pass_rate() -> None:
    # 2,000 repetitions of 48 independent uniform true-null p-values, one fixed seed. Under
    # independent true nulls Holm's family-wise rate is close to 0.0488, so about
    # 98 of 2,000 repetitions pass at least once (standard deviation about 9.6). The bound is
    # 0.05 + 3*sqrt(0.05*0.95/2000) = 0.0646, rounded up to 0.065. The lower guard (> 0) catches
    # an always-reject bug. Contrast, asserted nowhere: three independent per-family Holm
    # procedures at 0.05 each give about 1 - 0.95**3 = 0.143 for the same data.
    ids = confirmatory_hypothesis_ids()
    rng = random.Random(261014)
    repetitions = 2000
    passes = 0
    for _ in range(repetitions):
        p = {hid: rng.random() for hid in ids}
        adjusted = holm_adjust(p)
        if any(g3_passes(value) for value in adjusted.values()):
            passes += 1
    rate = passes / repetitions
    assert 0.0 < rate <= 0.065


def test_public_surface_is_closed() -> None:
    assert list(inspect.signature(holm_adjust_confirmatory).parameters) == ["p_by_id"]
    assert sorted(multiplicity.__all__) == sorted(
        [
            "EXPECTED_HYPOTHESES",
            "FAMILY_WISE_ALPHA",
            "MultiplicityError",
            "confirmatory_hypothesis_ids",
            "g3_passes",
            "holm_adjust",
            "holm_adjust_confirmatory",
        ]
    )
    doc = multiplicity.__doc__ or ""
    assert "scenario" in doc.lower()
    assert "never enter" in doc
    assert "does not exist" in doc
