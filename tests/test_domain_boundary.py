"""Boundary determinism suite (Phase 3, plan 03-05).

Per D-08 and TESTING_STRATEGY §5: empty, single-bar, and
warm-up-insufficient inputs each return an explicit invalid reason
and never raise or crash.

Mechanism-only placeholders (D-09): the entry point below is a
test-local placeholder Phase 4 replaces with real family logic.
MIN_BARS_TBD is a TBD marker per the plan (any threshold-looking
constant needs a RESEARCH_PROTOCOL source or a TBD marker).
"""

from __future__ import annotations

# TBD marker (plan 03-05): warm-up minimum is undecided until the
# family specs freeze in Phase 4. Three bars keeps the placeholder
# distinct from the single-bar case.
MIN_BARS_TBD = 3


def _placeholder_decide(candles: list[dict]) -> dict:
    """Placeholder harness entry point: invalid reasons, never raises."""
    if len(candles) == 0:
        return {"status": "INVALID", "reason": "EMPTY_INPUT"}
    if len(candles) == 1:
        return {"status": "INVALID", "reason": "SINGLE_BAR"}
    if len(candles) < MIN_BARS_TBD:
        return {"status": "INVALID", "reason": "WARMUP_INSUFFICIENT"}
    return {"status": "NO_TRADE", "reason": "MECHANISM_PLACEHOLDER_TBD"}


# --------------------------------------------------------------------------- #
# Test 1 — empty input returns an explicit invalid reason.
# --------------------------------------------------------------------------- #


def test_empty_input_returns_explicit_invalid_reason() -> None:
    """Beh. 1: empty candle list yields EMPTY_INPUT, no exception."""
    assert _placeholder_decide([]) == {"status": "INVALID", "reason": "EMPTY_INPUT"}


# --------------------------------------------------------------------------- #
# Test 2 — single-bar input returns an explicit invalid reason.
# --------------------------------------------------------------------------- #


def test_single_bar_returns_explicit_invalid_reason(phase3_candles) -> None:
    """Beh. 2: single-bar list yields SINGLE_BAR, no exception."""
    assert _placeholder_decide(phase3_candles[:1]) == {
        "status": "INVALID",
        "reason": "SINGLE_BAR",
    }


# --------------------------------------------------------------------------- #
# Test 3 — warm-up-insufficient input returns an explicit invalid reason.
# --------------------------------------------------------------------------- #


def test_warmup_insufficient_returns_explicit_invalid_reason(
    phase3_candles,
) -> None:
    """Beh. 3: too-few-bars input yields WARMUP_INSUFFICIENT, no exception."""
    assert _placeholder_decide(phase3_candles[: MIN_BARS_TBD - 1]) == {
        "status": "INVALID",
        "reason": "WARMUP_INSUFFICIENT",
    }


# --------------------------------------------------------------------------- #
# Test 4 — sufficient input never raises.
# --------------------------------------------------------------------------- #


def test_sufficient_input_never_raises(phase3_candles) -> None:
    """Beh. 4: at-threshold input returns a decision dict, no exception."""
    verdict = _placeholder_decide(phase3_candles[:MIN_BARS_TBD])
    assert verdict["status"] == "NO_TRADE"
    assert verdict["reason"] == "MECHANISM_PLACEHOLDER_TBD"
