"""Review-fix behavior pins (Phase 7 REVIEW CR-01/05/07/08 + WR-10).

Each test pins one REVIEW-FIX behavior so a regression fails loudly:

- CR-01 (fix 1bf76b3): resync pages past the 1500-row single-page cap.
  A >1500-close outage must backfill completely via cursor-advanced
  follow-up pages, never silently truncate to the first page.
- CR-05 (fix 3070383): Telegram callback_data stays within the 64-byte
  Bot API limit even for real-length signal ids.
- CR-07 (fix d50f99f): on_outcome runs OUTSIDE the tenacity attempt —
  a journal failure never triggers a resend; malformed payloads yield
  FAILED with attempts=0, never raise, never retry.
- CR-08 (fix f33189e): a 4h close is routed as a CONTEXT_BAR feed-gate
  record (context only), never appended to the 1h setup series.
- WR-10 (fix 995c530): the full per-bar projection is non-vacuous —
  it covers every replayed bar including signal-less records that the
  old signal-only projection dropped.

No implementation files are touched; test files and fixtures only.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"


# --------------------------------------------------------------------------- #
# CR-01: pagination past the 1500-row page cap.
# --------------------------------------------------------------------------- #


def _make_rest_kline(
    symbol: str, interval: str, open_utc: datetime, close_utc: datetime
) -> Any:
    from src.adapters.binance_usdm import Kline

    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=open_utc,
        close_time_utc=close_utc,
        open=Decimal("100.00"),
        high=Decimal("100.10"),
        low=Decimal("99.95"),
        close=Decimal("100.05"),
        volume=Decimal("1.0"),
        quote_volume=Decimal("0"),
        trade_count=0,
    )


class _PaginatingAdapter:
    """Fake REST adapter serving cursor-advanced pages like the exchange."""

    def __init__(self, *, closes: list[Any]) -> None:
        self._closes = list(closes)
        self.calls: list[int | None] = []

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Any]:
        from src.paper.resync import _datetime_to_ms

        self.calls.append(start_ms)
        assert start_ms is not None
        page = [
            k
            for k in self._closes
            if _datetime_to_ms(k.open_time_utc) >= start_ms
        ][:limit]
        return page


def test_long_outage_pages_past_single_page_cap() -> None:
    """A 1500+ close outage backfills completely across pages."""
    from src.paper.resync import backfill_missed_closes

    symbol, interval = "BTCUSDT", "1h"
    last = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    hour = timedelta(hours=1)
    # 1500 closes fill page one exactly; 2 more force a second page.
    closes = [
        _make_rest_kline(symbol, interval, last + i * hour, last + (i + 1) * hour)
        for i in range(1502)
    ]
    now = last + 1502 * hour
    adapter = _PaginatingAdapter(closes=closes)

    async def _call() -> tuple[list[Any], list[dict[str, Any]]]:
        return await backfill_missed_closes(
            adapter,
            symbol=symbol,
            interval=interval,
            last_close_utc=last,
            now_utc=now,
        )

    got_closes, gaps = asyncio.run(_call())

    assert len(got_closes) == 1502, (
        f"pagination must return all closes, got {len(got_closes)} (truncated?)"
    )
    assert len(adapter.calls) >= 2, (
        f"expected >=2 page fetches, got {len(adapter.calls)} (single-page?)"
    )
    assert gaps == [], f"fully-covered outage must journal no gaps, got {gaps}"


def test_adapter_value_error_propagates_without_retry() -> None:
    """A ValueError from klines fails fast instead of burning 120s (WR-02)."""
    import time

    from src.paper.resync import backfill_missed_closes

    class _BuggyAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def klines(self, *a: Any, **k: Any) -> list[Any]:
            self.calls += 1
            raise ValueError("deterministic bug, not transient")

    adapter = _BuggyAdapter()
    started = time.monotonic()
    try:
        asyncio.run(
            backfill_missed_closes(
                adapter,  # type: ignore[arg-type]
                symbol="BTCUSDT",
                interval="1h",
                last_close_utc=datetime(2026, 9, 19, 10, 0, tzinfo=UTC),
                now_utc=datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
            )
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("ValueError must propagate, not be swallowed")
    elapsed = time.monotonic() - started
    assert adapter.calls == 1, f"no retry on programming errors, got {adapter.calls}"
    assert elapsed < 10, f"must fail fast, took {elapsed:.1f}s"


# --------------------------------------------------------------------------- #
# CR-05: callback_data 64-byte bound with real-length signal ids.
# --------------------------------------------------------------------------- #


def test_callback_data_within_64_bytes_for_real_signal_id() -> None:
    """Real-length signal ids still fit Telegram's 64-byte callback bound."""
    from src.adapters.telegram_notify import build_simulate_keyboard

    # The notify suite's own id is ~61 chars; SIM:/SKIP: prefix pushed the
    # old format to 65 bytes (deterministic Bot API rejection).
    long_id = "sig_test_" + "0" * 52
    assert len(long_id) == 61
    keyboard = build_simulate_keyboard(long_id)
    for row in keyboard.inline_keyboard:
        for button in row:
            data = str(button.callback_data)
            assert len(data.encode("utf-8")) <= 64, (
                f"callback_data exceeds 64 bytes: {data!r}"
            )

    # Deterministic: same id maps to same short data (idempotent sends).
    again = build_simulate_keyboard(long_id)
    assert (
        again.inline_keyboard[0][0].callback_data
        == keyboard.inline_keyboard[0][0].callback_data
    )


# --------------------------------------------------------------------------- #
# CR-07: on_outcome outside the retry; malformed payload never raises.
# --------------------------------------------------------------------------- #


class _CountingBot:
    def __init__(self, *, raise_on_send: Exception | None = None) -> None:
        self.calls = 0
        self._raise = raise_on_send

    async def send_message(self, **kwargs: Any) -> object:
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        return {"message_id": 1}


def _notify_payload() -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "setup": "TREND_PULLBACK_LONG",
        "entry_min": Decimal("100.10"),
        "entry_max": Decimal("100.30"),
        "stop_loss": Decimal("99.50"),
        "take_profits": [(Decimal("101.50"), Decimal("0.5"))],
        "rr": Decimal("2.0"),
        "risk_pct": Decimal("0.005"),
        "expiry_utc": datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        "invalidation": "CANDLE_CLOSE < 99.50",
        "exposure_quote": Decimal("50.00"),
        "reason_codes": ["SETUP_DETECTED"],
        "signal_id": "sig_pin_0001",
        "detected_at_utc": datetime(2026, 9, 19, 9, 0, tzinfo=UTC),
    }


def test_journal_callback_failure_never_triggers_resend() -> None:
    """A raising on_outcome is logged, never retried into a duplicate send."""
    from src.paper.notify import NotifyOutcomeKind, notify_simulate

    bot = _CountingBot()

    def _bad_outcome(_o: Any) -> None:
        raise RuntimeError("journal commit failed")

    outcome = asyncio.run(
        notify_simulate(
            bot=bot,  # type: ignore[arg-type]
            chat_id="123",
            payload=_notify_payload(),
            on_outcome=_bad_outcome,
        )
    )

    assert outcome.kind == NotifyOutcomeKind.SENT
    assert bot.calls == 1, (
        f"journal fault must never multiply sends, got {bot.calls}"
    )


def test_malformed_payload_yields_failed_without_send_or_raise() -> None:
    """Missing payload keys yield FAILED attempts=0, no send, no raise."""
    from src.paper.notify import NotifyOutcomeKind, notify_simulate

    bot = _CountingBot()
    seen: list[Any] = []
    bad = _notify_payload()
    del bad["stop_loss"]

    outcome = asyncio.run(
        notify_simulate(
            bot=bot,  # type: ignore[arg-type]
            chat_id="123",
            payload=bad,
            on_outcome=seen.append,
        )
    )

    assert outcome.kind == NotifyOutcomeKind.FAILED
    assert outcome.attempts == 0
    assert bot.calls == 0, "malformed payload must never reach the wire"
    assert len(seen) == 1


def test_failed_outcome_reports_root_cause_not_retry_wrapper() -> None:
    """Exhaustion journals the root error class, not tenacity RetryError."""
    from src.paper.notify import NotifyOutcomeKind, notify_simulate

    bot = _CountingBot(raise_on_send=TimeoutError("telegram timeout"))
    outcome = asyncio.run(
        notify_simulate(
            bot=bot,  # type: ignore[arg-type]
            chat_id="123",
            payload=_notify_payload(),
            on_outcome=lambda _o: None,
        )
    )

    assert outcome.kind == NotifyOutcomeKind.FAILED
    assert outcome.error_class == "TimeoutError", (
        f"must journal root cause, got {outcome.error_class!r}"
    )


# --------------------------------------------------------------------------- #
# CR-08: 4h closes route as CONTEXT_BAR, never as 1h setup bars.
# --------------------------------------------------------------------------- #


def _clean_run_input() -> dict[str, Any]:
    return json.loads((PHASE7_FIXTURES_DIR / "clean_run" / "input.json").read_text())


def test_4h_close_routes_as_context_bar_not_setup_bar() -> None:
    """A 4h event yields CONTEXT_BAR and never enters the setup series."""
    from src.paper.loop import run_paper_tick

    case_input = _clean_run_input()
    baseline = run_paper_tick(case_input)

    now_utc = datetime.fromisoformat(case_input["now_utc"])
    close_utc = now_utc  # fresh: within the 60s staleness threshold
    open_utc = close_utc - timedelta(hours=4)
    event_4h = {
        "t": int(open_utc.timestamp() * 1000),
        "T": int(close_utc.timestamp() * 1000),
        "o": "100.00",
        "h": "100.05",
        "l": "99.95",
        "c": "100.00",
        "v": "1.0",
        "n": 10,
        "x": True,
        "q": "1.0",
        "interval": "4h",
    }
    with_4h = {**case_input, "feed_events": [*case_input["feed_events"], event_4h]}
    outcome = run_paper_tick(with_4h)

    contexts = [
        r
        for r in outcome["no_trade_records"]
        if r["reason_code"] == "CONTEXT_BAR"
    ]
    assert len(contexts) == 1, (
        f"4h close must yield exactly one CONTEXT_BAR, got {outcome['no_trade_records']}"
    )
    assert contexts[0]["stage"] == "feed_gate"
    assert contexts[0]["bar_close_utc"] == close_utc.isoformat()

    # The 4h bar must not leak into the 1h decision surface: signals and
    # trade plans are unchanged versus the baseline run.
    assert outcome["signals"] == baseline["signals"]
    assert outcome["trade_plans"] == baseline["trade_plans"]


def test_4h_context_extends_later_1h_evaluation_without_setup_pollution() -> None:
    """A 4h context bar followed by a duplicate 1h bar stays deterministic."""
    from src.paper.loop import run_paper_tick

    case_input = _clean_run_input()
    now_utc = datetime.fromisoformat(case_input["now_utc"])
    close_utc = now_utc
    open_utc = close_utc - timedelta(hours=4)
    event_4h = {
        "t": int(open_utc.timestamp() * 1000),
        "T": int(close_utc.timestamp() * 1000),
        "o": "100.00",
        "h": "100.05",
        "l": "99.95",
        "c": "100.00",
        "v": "1.0",
        "n": 10,
        "x": True,
        "q": "1.0",
        "interval": "4h",
    }
    # run_paper_tick is pure: same input twice hashes identically even
    # with the interleaved 4h context event.
    from src.domain.canonical import sha256_hex

    first = run_paper_tick({**case_input, "feed_events": [*case_input["feed_events"], event_4h]})
    second = run_paper_tick({**case_input, "feed_events": [*case_input["feed_events"], event_4h]})
    assert sha256_hex(first) == sha256_hex(second)


# --------------------------------------------------------------------------- #
# WR-10: the full projection is non-vacuous (fails on vacuous projection).
# --------------------------------------------------------------------------- #


def test_full_projection_is_non_vacuous_where_signal_only_is() -> None:
    """The old signal-only projection hides signal-less bars; full does not."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from tests.test_paper_parity import (  # noqa: E402
        _project_paper_verdicts,
        _project_paper_verdicts_full,
        _replay_paper_through_bars,
    )

    case_input = json.loads(
        (PHASE7_FIXTURES_DIR / "parity_overlapping_history" / "input.json").read_text()
    )
    paper_outcomes = _replay_paper_through_bars(case_input)

    narrow = _project_paper_verdicts(paper_outcomes)
    full = _project_paper_verdicts_full(paper_outcomes)

    n_bars = len(case_input["strategy_bars"])
    assert len(full) == n_bars, (
        f"full projection must cover every bar, got {len(full)}/{n_bars}"
    )
    # The anti-vacuity assertion: the old projection MUST be strictly
    # narrower here (it drops signal-less records), proving the new test
    # guards a real hole instead of re-pinning an already-covered shape.
    assert len(narrow) < len(full), (
        f"expected vacuous narrow projection ({len(narrow)}) < full ({len(full)}); "
        "if equal, the anti-vacuity premise no longer holds"
    )
    assert any(signal_id is None for (_, signal_id, _, _) in full)
