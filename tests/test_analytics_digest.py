"""Determinism guards for the analytics core (Phase 10, plan 10-01, D-01, T-10-01).

The same inputs + seed give a byte-identical section digest regardless of input
order or interpreter hash seed; a different seed, resample count, or evidence
kind changes it.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.analytics.excursion import ExcursionSection, build_excursion_section
from src.analytics.inputs import normalize_backtest
from src.analytics.types import EvidenceKind, TradeOutcome
from src.core.types import Candle

from tests.phase10_helpers import D, load_expected, load_input, make_candles, make_trade_record

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE = "digest_regeneration"


def _build(
    *,
    reverse: bool = False,
    base_seed: int | None = None,
    resamples: int | None = None,
    evidence: EvidenceKind = EvidenceKind.BACKTEST,
) -> tuple[ExcursionSection, dict[str, Any]]:
    data = load_input(CASE)
    expected = load_expected(CASE)
    rows = list(reversed(data["trades"])) if reverse else list(data["trades"])
    candle_rows = list(reversed(data["candles"])) if reverse else list(data["candles"])
    outcomes: list[TradeOutcome] = list(
        normalize_backtest([make_trade_record(**row) for row in rows]).outcomes
    )
    if evidence is not EvidenceKind.BACKTEST:
        outcomes = [dataclasses.replace(o, evidence=evidence) for o in outcomes]
    candles: list[Candle] = make_candles(candle_rows)
    section = build_excursion_section(
        outcomes,
        {"BTCUSDT": candles},
        evidence=evidence,
        base_seed=expected["base_seed"] if base_seed is None else base_seed,
        resamples=expected["resamples"] if resamples is None else resamples,
    )
    return section, expected


def test_fixture_numbers_hold_before_the_digest_is_trusted() -> None:
    section, expected = _build()
    want = expected["trades"]["T-DR-2"]
    by_id = {t.trade_id: t for t in section.per_trade}
    short = by_id["T-DR-2"]
    assert short.mfe_price == D(want["mfe_price"])
    assert short.mae_price == D(want["mae_price"])
    assert short.mfe_r == D(want["mfe_r"])
    assert short.mae_r == D(want["mae_r"])
    assert short.time_to_mfe_s == D(want["time_to_mfe_s"])
    assert short.time_to_mae_s == D(want["time_to_mae_s"])
    assert short.holding_s == D(want["holding_s"])
    assert section.n_outcomes == expected["section"]["n_outcomes"]
    assert section.n_measured == expected["section"]["n_measured"]
    assert section.incomplete == tuple(
        (reason, count) for reason, count in expected["section"]["incomplete"]
    )


def test_section_digest_is_pinned_and_regenerates_byte_identically() -> None:
    first, expected = _build()
    second, _ = _build()
    shuffled, _ = _build(reverse=True)
    assert len(first.digest()) == 64
    assert first.digest() == second.digest()
    assert first.digest() == shuffled.digest()  # order-independent via trade_id sort
    assert first.digest() == expected["section_digest"]


def test_seed_resamples_and_evidence_kind_change_the_digest() -> None:
    base, _ = _build()
    other_seed, _ = _build(base_seed=20260930)
    other_resamples, _ = _build(resamples=101)
    paper, _ = _build(evidence=EvidenceKind.PAPER)
    digests = {base.digest(), other_seed.digest(), other_resamples.digest(), paper.digest()}
    assert len(digests) == 4


def test_digest_is_independent_of_interpreter_hash_seed() -> None:
    """A fresh process under different PYTHONHASHSEED values reproduces the pin."""
    script = (
        "from tests.test_analytics_digest import _build\n"
        "print(_build()[0].digest())\n"
    )
    expected = load_expected(CASE)["section_digest"]
    for hash_seed in ("1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == expected
