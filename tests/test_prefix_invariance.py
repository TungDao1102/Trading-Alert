"""Prefix-invariance determinism suite (Phase 3, plan 03-05).

Per D-08: the same candle prefix embedded in two different longer
inputs must yield byte-identical prefix outputs (compared through
canonical digests).

Mechanism-only placeholders (D-09): shares the per-candle SignalId
mapping with the no-lookahead suite; Phase 4 replaces the mapping
with real family logic while these invariants stay green.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.domain.canonical import sha256_hex
from src.domain.ids import make_signal_id

TIMEFRAME_SECONDS = {"1m": 60, "1h": 3600, "4h": 14400}

STRATEGY_ID = "trend-pullback"
STRATEGY_VERSION = "v1.0.0"
PARAMETER_SET_ID = "baseline-v1"


def _close_time(candle: dict) -> datetime:
    """Close time of a fixture candle (open + one timeframe interval)."""
    step = TIMEFRAME_SECONDS[candle["timeframe"]]
    opened = datetime.fromisoformat(candle["open_time_utc"])
    return opened + timedelta(seconds=step)


def _signal_entries(candles: list[dict]) -> list[tuple[str, str]]:
    """Placeholder pipeline output: one (close_iso, signal_id) per candle."""
    entries = []
    for candle in candles:
        close = _close_time(candle)
        sid = make_signal_id(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_set_id=PARAMETER_SET_ID,
            symbol=candle["symbol"],
            source_timeframe=candle["timeframe"],
            source_candle_close_utc=close,
            setup_fingerprint=sha256_hex(dict(candle)),
        )
        entries.append((close.isoformat(), sid))
    return entries


def _synthetic_bar(symbol: str, opened: datetime, price: str) -> dict:
    """Build a bar continuing the fixture series shape."""
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "open_time_utc": opened.isoformat(),
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": "1.0",
    }


# --------------------------------------------------------------------------- #
# Test 1 — shared prefix embedded in two longer inputs.
# --------------------------------------------------------------------------- #


def test_shared_prefix_embedded_in_two_inputs(phase3_candles) -> None:
    """Beh. 1: one shared prefix in two longer inputs, identical digests.

    The prefix sits at different offsets in the two inputs; its
    outputs must still compare byte-identical.
    """
    prefix = phase3_candles[:3]
    head_open = datetime.fromisoformat(prefix[0]["open_time_utc"])
    tail_open = datetime.fromisoformat(prefix[-1]["open_time_utc"])
    head = [_synthetic_bar("BTCUSDT", head_open - timedelta(hours=1), "49500.00")]
    tail_a = [_synthetic_bar("BTCUSDT", tail_open + timedelta(hours=1), "51000.00")]
    tail_b = [_synthetic_bar("BTCUSDT", tail_open + timedelta(hours=1), "49000.00")]
    input_a = head + prefix + tail_a
    input_b = prefix + tail_b
    out_a = _signal_entries(input_a)
    out_b = _signal_entries(input_b)
    # Prefix occupies positions 1..3 in A and 0..2 in B.
    assert [sid for _, sid in out_a[1:4]] == [sid for _, sid in out_b[0:3]]
    assert [close for close, _ in out_a[1:4]] == [close for close, _ in out_b[0:3]]


# --------------------------------------------------------------------------- #
# Test 2 — full-run digest stability over identical input.
# --------------------------------------------------------------------------- #


def test_full_run_digest_stable_over_identical_input(phase3_candles) -> None:
    """Beh. 2: two runs over the same input are digest-identical.

    Pins determinism of the mapping itself (no wall-clock, no ordering
    nondeterminism) so the prefix comparisons above are meaningful.
    """
    first = _signal_entries(phase3_candles)
    second = _signal_entries(phase3_candles)
    assert first == second


def test_stateful_variant_is_detected_by_digest_comparison(phase3_candles) -> None:
    """Canary (WR-09): hidden run-to-run state changes digests.

    A deliberately stateful helper (module-global call counter folded
    into the fingerprint) yields DIFFERENT digests across two runs over
    identical input — proving Beh. 2's comparison is sensitive to the
    nondeterminism bug class before Phase 4 swaps in real logic.
    """
    calls = {"n": 0}

    def _stateful_entries(candles: list[dict]) -> list[tuple[str, str]]:
        entries = []
        for candle in candles:
            calls["n"] += 1
            close = _close_time(candle)
            sid = make_signal_id(
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                parameter_set_id=PARAMETER_SET_ID,
                symbol=candle["symbol"],
                source_timeframe=candle["timeframe"],
                source_candle_close_utc=close,
                setup_fingerprint=sha256_hex(dict(candle)) + f":{calls['n']}",
            )
            entries.append((close.isoformat(), sid))
        return entries

    first = _stateful_entries(phase3_candles)
    second = _stateful_entries(phase3_candles)
    assert first != second
