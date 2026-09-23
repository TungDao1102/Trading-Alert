"""No-lookahead determinism suite (Phase 3, plan 03-05).

Per D-08 and TESTING_STRATEGY §3: appending arbitrary bars after time T
must never change the canonical bytes of outputs at or before T.

Mechanism-only placeholders (D-09): outputs are content-hash SignalIds
per the D-03 scheme (make_signal_id keyed by source_candle_close_utc),
with the candle body as the opaque setup fingerprint Phase 4 will
widen. No strategy thresholds, no family constants.
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
    """Placeholder pipeline output: one (close_iso, signal_id) per candle.

    Each output references ONLY its own source candle (closed-candle
    input by construction) — the property the no-lookahead tests pin.
    """
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
    """Build a post-T bar continuing the fixture series shape."""
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
# Test 1 — appended bars never change prefix digests.
# --------------------------------------------------------------------------- #


def test_appended_bars_never_change_prefix_digests(phase3_candles) -> None:
    """Beh. 1: outputs at or before T are byte-identical after appends.

    Prefix outputs hashed through canonical_bytes-equivalent digests
    (sha256_hex) must match before and after appending extra bars.
    """
    prefix = phase3_candles[:3]
    last_open = datetime.fromisoformat(prefix[-1]["open_time_utc"])
    extra = [
        _synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "50600.00"),
        _synthetic_bar("BTCUSDT", last_open + timedelta(hours=2), "50700.00"),
    ]
    before = _signal_entries(prefix)
    after = _signal_entries(prefix + extra)
    assert [sid for _, sid in after[:3]] == [sid for _, sid in before]
    assert [close for close, _ in after[:3]] == [close for close, _ in before]


# --------------------------------------------------------------------------- #
# Test 2 — same prefix under different suffixes stays identical.
# --------------------------------------------------------------------------- #


def test_same_prefix_different_suffixes_identical(phase3_candles) -> None:
    """Beh. 2: the same prefix yields identical digests under any suffix."""
    prefix = phase3_candles[:2]
    last_open = datetime.fromisoformat(prefix[-1]["open_time_utc"])
    suffix_a = [_synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "51000.00")]
    suffix_b = [_synthetic_bar("BTCUSDT", last_open + timedelta(hours=1), "49000.00")]
    out_a = _signal_entries(prefix + suffix_a)
    out_b = _signal_entries(prefix + suffix_b)
    assert [sid for _, sid in out_a[:2]] == [sid for _, sid in out_b[:2]]
    # Sanity: the comparison is sensitive — suffix outputs differ.
    assert out_a[2][1] != out_b[2][1]
