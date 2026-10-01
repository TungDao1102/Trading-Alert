"""Pin the paper-loop feed fail-closed gates (Phase 7, plan 07-01, Task 2).

Per D-01/D-02 and PATTERNS §Gates: the paper loop MUST reject unsafe
feed states (insufficient warmup, stale data) BEFORE the engine chain
runs. Rejection emits a single no_trade_record with stage="feed_gate"
and a canonical RejectionReason code (WARMUP_INSUFFICIENT or DATA_STALE).

These tests verify:
1. Truncated history -> WARMUP_INSUFFICIENT before evaluate().
2. now_utc far past last close -> DATA_STALE before evaluate().
3. A fresh event after a stale event resumes evaluation (no restart).
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.canonical import sha256_hex  # noqa: E402
from src.paper import run_paper_tick  # noqa: E402
from src.paper.loop import STALENESS_THRESHOLD_SECONDS  # noqa: E402

FIXTURE_DIR = Path("tests/fixtures/phase7")


def _load_case(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name / "input.json").read_text(encoding="utf-8"))


def _load_expected(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name / "expected.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Test 1 — warmup insufficient emits WARMUP_INSUFFICIENT (D-02 fail-closed).
# --------------------------------------------------------------------------- #


def test_warmup_invalid_emits_warmup_insufficient() -> None:
    """Truncated history → check_feature_validity fires BEFORE evaluate()."""
    case = _load_case("warmup_invalid_no_trade")
    expected = _load_expected("warmup_invalid_no_trade")

    outcome = run_paper_tick(case)

    assert outcome["signals"] == []
    assert outcome["trade_plans"] == []
    assert len(outcome["no_trade_records"]) == 1
    record = outcome["no_trade_records"][0]
    assert record["reason_code"] == "WARMUP_INSUFFICIENT"
    assert record["stage"] == "feed_gate"
    assert outcome["feed_events_processed"] == 1
    assert outcome["feed_events_dropped"] == 0

    assert sha256_hex(outcome) == expected["outcome_digest"]


# --------------------------------------------------------------------------- #
# Test 2 — stale feed emits DATA_STALE (D-02 fail-closed).
# --------------------------------------------------------------------------- #


def test_feed_stale_emits_data_stale() -> None:
    """now_utc >> last close → check_feed_freshness fires BEFORE evaluate()."""
    case = _load_case("feed_stale_no_trade")
    expected = _load_expected("feed_stale_no_trade")

    # Sanity-check the fixture: the staleness gap must exceed the
    # gate threshold, otherwise the test is tautological.
    now_utc = datetime.fromisoformat(case["now_utc"])
    last_close_str = case["warmed_up_1h"][-1]["close_time_utc"]
    last_close_utc = datetime.fromisoformat(last_close_str)
    gap_seconds = (now_utc - last_close_utc).total_seconds()
    assert gap_seconds > STALENESS_THRESHOLD_SECONDS, (
        f"fixture gap ({gap_seconds}s) must exceed "
        f"STALENESS_THRESHOLD_SECONDS ({STALENESS_THRESHOLD_SECONDS}s)"
    )

    outcome = run_paper_tick(case)

    assert outcome["signals"] == []
    assert outcome["trade_plans"] == []
    assert len(outcome["no_trade_records"]) == 1
    record = outcome["no_trade_records"][0]
    assert record["reason_code"] == "DATA_STALE"
    assert record["stage"] == "feed_gate"
    assert outcome["feed_events_processed"] == 1
    assert outcome["feed_events_dropped"] == 0

    assert sha256_hex(outcome) == expected["outcome_digest"]


# --------------------------------------------------------------------------- #
# Test 3 — recovery after stale resumes evaluation without restart.
# --------------------------------------------------------------------------- #


def test_recovery_after_stale_resumes_evaluation() -> None:
    """A stale event then a fresh event on the same input must:
    - emit DATA_STALE for the stale event (feed_gate stage)
    - proceed past the feed gate for the fresh event (no DATA_STALE
      from the staleness check)

    The stale check is per-event, so a fresh event is NOT latched
    behind the stale prior. This is the recovery contract.

    Implementation: two separate run_paper_tick calls. The second
    call re-delivers the last warmed-up bar as the fresh event with
    now_utc set 1 second past its close — well within the 60s
    staleness threshold. No gap is introduced because the fresh
    event's bar is already in the warmed-up history.
    """
    base = _load_case("feed_stale_no_trade")

    # Call 1: stale event → DATA_STALE.
    stale_outcome = run_paper_tick(base)
    assert len(stale_outcome["no_trade_records"]) == 1
    assert stale_outcome["no_trade_records"][0]["reason_code"] == "DATA_STALE"
    assert stale_outcome["no_trade_records"][0]["stage"] == "feed_gate"

    # Call 2: re-deliver the last warmed-up bar as a fresh event.
    # now_utc is set 1 second past the bar's close — well within
    # the 60s staleness threshold. The bar is already in warmed_up_1h,
    # so no gap is introduced.
    last_bar = base["warmed_up_1h"][-1]
    last_close_utc = datetime.fromisoformat(last_bar["close_time_utc"])
    last_open_utc = datetime.fromisoformat(last_bar["open_time_utc"])
    now_utc = last_close_utc + timedelta(seconds=1)

    fresh_event = {
        "t": int(last_open_utc.timestamp() * 1000),
        "T": int(last_close_utc.timestamp() * 1000),
        "o": last_bar["open"],
        "h": last_bar["high"],
        "l": last_bar["low"],
        "c": last_bar["close"],
        "v": last_bar["volume"],
        "n": 100,
        "x": True,
        "q": last_bar["volume"],
    }

    case2 = deepcopy(base)
    case2["feed_events"] = [fresh_event]
    case2["now_utc"] = now_utc.isoformat()
    # Remove the last warmed-up bar — the fresh event re-delivers it,
    # so including it in warmed_up_1h would create a duplicate
    # open_time_utc in the snapshot (same pattern as clean_run).
    case2["warmed_up_1h"] = base["warmed_up_1h"][:-1]

    fresh_outcome = run_paper_tick(case2)

    # The fresh event passes the staleness gate (gap = 1s < 60s).
    # It may still emit NO_TRADE from the engine (regime/setup gates),
    # but NOT from the feed_gate stage.
    feed_gate_records = [r for r in fresh_outcome["no_trade_records"] if r["stage"] == "feed_gate"]
    assert len(feed_gate_records) == 0, (
        f"fresh event should pass feed gates; got {feed_gate_records}"
    )

    # And the outcome is byte-deterministic under frozen clock.
    case2_again = deepcopy(case2)
    fresh_outcome_again = run_paper_tick(case2_again)
    assert sha256_hex(fresh_outcome) == sha256_hex(fresh_outcome_again)


# --------------------------------------------------------------------------- #
# Threshold constant exists (PATTERNS §Gates: explicit, exported).
# --------------------------------------------------------------------------- #


def test_staleness_threshold_constant_is_exported() -> None:
    """STALENESS_THRESHOLD_SECONDS must be importable and positive."""
    assert isinstance(STALENESS_THRESHOLD_SECONDS, int)
    assert STALENESS_THRESHOLD_SECONDS > 0
    # Project policy: feed stale threshold defaults to 60 seconds
    # (RESEARCH §Gates); paper-loop tightens to 60 for 1H cadence.
    assert STALENESS_THRESHOLD_SECONDS == 60


# --------------------------------------------------------------------------- #
# Edge: an event safely within the staleness threshold passes the gate.
# --------------------------------------------------------------------------- #


def test_feed_freshness_within_threshold_passes() -> None:
    """An event with close_time_utc == now_utc - (threshold - 1s) passes
    the staleness gate. Uses a 1-second safety margin to avoid
    floating-point precision loss in the ms timestamp conversion."""
    base = _load_case("clean_run")
    case = deepcopy(base)

    now_utc = datetime.fromisoformat(case["now_utc"])
    safe_close = now_utc - timedelta(seconds=STALENESS_THRESHOLD_SECONDS - 1)

    event = case["feed_events"][1]  # the closed event in clean_run
    event["T"] = int(safe_close.timestamp() * 1000)
    event["t"] = event["T"] - 3_600_000
    case["feed_events"] = [event]
    case["now_utc"] = now_utc.isoformat()

    outcome = run_paper_tick(case)
    feed_gate_records = [r for r in outcome["no_trade_records"] if r["stage"] == "feed_gate"]
    assert len(feed_gate_records) == 0, (
        f"event within threshold should pass feed gates; got {feed_gate_records}"
    )
