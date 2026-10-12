"""Operator entrypoint of the test-only SHADOW rehearsal (Phase 16, plan 16-39, REV-03).

Run from the repository root::

    uv run python scripts/shadow_rehearsal.py --dry-run --out <evidence.json>

What it is. A single-file tool that takes ONE clearly labelled test signal (`TEST SIGNAL`, ids
with the `TEST-` prefix) through the SHADOW chain: alert, APPROVE, confirmation card, CONFIRM,
the journal and state transitions, and a simulated position opened by the same fill driver. Every
row it writes is marked `test_only`. It is a separate entry from the production paper path: it
does not call the production start gate, does not read the paper-start allowlist and does not pin
an epoch. It runs once per rehearsal database and writes one scrubbed evidence file.

`--dry-run` (the CI mode) drives the chain over the in-memory stores, the fake bot and scripted
public minutes of the repository's test fakes on a virtual clock. It never touches the network
and never waits; its evidence carries proof class `FAKE`.

Exit codes::

    0  the run completed: the position opened and the label was seen (evidence written)
    1  the run ended without an opened position, or failed (evidence written when possible)
    2  refused before any work (usage)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.adapters.binance_public import FundingTick, Kline, MarkKline  # noqa: E402
from src.adapters.telegram_notify import TelegramTextBot  # noqa: E402
from src.domain.approval import Approval  # noqa: E402
from src.domain.registry import load_parameter_set  # noqa: E402
from src.domain.signal import Signal  # noqa: E402
from src.domain.trade_plan import TradePlan  # noqa: E402
from src.paper.rehearsal import (  # noqa: E402
    RehearsalError,
    RehearsalMode,
    RehearsalResult,
    RehearsalSettings,
    run_rehearsal,
)
from src.paper.shadow_runtime import ShadowCoordinator, ShadowRuntimeStores  # noqa: E402
from src.risk.types import ConstraintSnapshot  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

_MINUTE = timedelta(minutes=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# A fixed start for the virtual clock of the dry run: the output is reproducible.
DRY_RUN_START = datetime(2026, 10, 9, 3, 0, 5, tzinfo=UTC)
DRY_RUN_SYMBOL = "BTCUSDT"
DRY_RUN_PRICE = Decimal("50000")
DRY_RUN_MINUTES = 120
# The seconds a human would think before pressing each button (virtual time only).
DRY_RUN_THINK_SECONDS = {"APR": 20, "CNF": 10}


class UsageError(Exception):
    """A malformed command line (exit status 2)."""


class VirtualClock:
    """A movable clock whose `sleep` advances it instead of waiting (dry run and tests)."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)


def _ms(moment: datetime) -> int:
    return (moment - _EPOCH) // timedelta(milliseconds=1)


class ScriptedPublic:
    """Recorded flat minutes around a fixed price: the public adapter surface the chain reads."""

    def __init__(self, start: datetime, symbol: str, price: Decimal) -> None:
        first = start.replace(second=0, microsecond=0) - _MINUTE
        self._symbol = symbol
        self._trade: list[Kline] = []
        self._mark: list[MarkKline] = []
        for index in range(DRY_RUN_MINUTES):
            opened = first + _MINUTE * index
            closed = opened + timedelta(seconds=59, milliseconds=999)
            high, low = price + Decimal("5"), price - Decimal("5")
            self._trade.append(
                Kline(
                    symbol=symbol,
                    interval="1m",
                    open_time_utc=opened,
                    close_time_utc=closed,
                    open=price,
                    high=high,
                    low=low,
                    close=price,
                    volume=Decimal("1"),
                    quote_volume=Decimal("1"),
                    trade_count=1,
                )
            )
            self._mark.append(
                MarkKline(
                    symbol=symbol,
                    interval="1m",
                    open_time_utc=opened,
                    close_time_utc=closed,
                    open=price,
                    high=high,
                    low=low,
                    close=price,
                    price_tick_count=1,
                )
            )
        self._funding = [FundingTick(symbol, start - timedelta(hours=2), Decimal("0.0001"), price)]

    @staticmethod
    def _window(
        rows: Sequence[Any], symbol: str, start_ms: int | None, end_ms: int | None, limit: int
    ) -> list[Any]:
        picked = [
            r
            for r in rows
            if r.symbol == symbol
            and (start_ms is None or _ms(r.open_time_utc) >= start_ms)
            and (end_ms is None or _ms(r.open_time_utc) <= end_ms)
        ]
        # Like the exchange: without a start time the newest rows before the end are returned.
        return picked[:limit] if start_ms is not None else picked[-limit:]

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        return cast(list[Kline], self._window(self._trade, symbol, start_ms, end_ms, limit))

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        return cast(list[MarkKline], self._window(self._mark, symbol, start_ms, end_ms, limit))

    async def funding_rate(
        self,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[FundingTick]:
        return [
            t
            for t in self._funding
            if t.symbol == symbol
            and (start_ms is None or _ms(t.funding_time_utc) >= start_ms)
            and (end_ms is None or _ms(t.funding_time_utc) <= end_ms)
        ][:limit]


class FixedConstraints:
    """One fixed exchange constraint snapshot (the dry run needs no exchangeInfo)."""

    def __init__(self, symbol: str, observed_at_utc: datetime) -> None:
        self._snapshot = ConstraintSnapshot(
            symbol=symbol,
            price_tick_size=Decimal("0.1"),
            quantity_step_size=Decimal("0.001"),
            min_quantity=Decimal("0.001"),
            min_notional=Decimal("100"),
            metadata_observed_at_utc=observed_at_utc,
        )

    def snapshot_for(self, symbol: str, at_utc: datetime) -> ConstraintSnapshot:
        return self._snapshot


def _memory_stores() -> ShadowRuntimeStores:
    """The in-memory stores of the repository's fakes plus the three single-row readers."""
    from tests.shadow_fakes import InMemoryShadowStores

    class MemoryStores(InMemoryShadowStores):
        def get_signal(self, signal_id: str) -> Signal | None:
            return self.signals.get(signal_id)

        def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None:
            return self.plans.get(trade_plan_id)

        def get_approval(self, approval_id: str) -> Approval | None:
            return self.approvals.get(approval_id)

    return cast(ShadowRuntimeStores, MemoryStores())


def _dry_run_press(
    clock: VirtualClock, chat_id: int
) -> Callable[[ShadowCoordinator, str, str], Awaitable[None]]:
    """The operator's presses of a dry run: PTB-shaped updates through the real callback path."""
    from src.adapters.telegram_callbacks import on_callback
    from tests.shadow_fakes import make_callback_update

    async def press(coordinator: ShadowCoordinator, data: str, query_id: str) -> None:
        clock.advance(DRY_RUN_THINK_SECONDS[data.split(":", 1)[0]])
        update = make_callback_update(data=data, chat_id=chat_id, query_id=query_id)
        await on_callback(update, cast(Any, None), **coordinator.callback_kwargs())

    return press


async def run_dry_rehearsal(
    out: Path,
    *,
    stores: ShadowRuntimeStores | None = None,
    bot: TelegramTextBot | None = None,
    environ: Mapping[str, str] | None = None,
) -> RehearsalResult:
    """The rehearsal over fakes on a virtual clock (proof class FAKE)."""
    from tests.shadow_fakes import CHAT_ID, FakeBot

    clock = VirtualClock(DRY_RUN_START)
    settings = RehearsalSettings(
        symbol=DRY_RUN_SYMBOL,
        chat_id=CHAT_ID,
        initial_equity=Decimal("10000"),
        risk_rate=Decimal("0.005"),
        minute_poll_interval_seconds=2,
        minute_close_lag_seconds=5,
        confirm_ttl_seconds=60,
    )
    return await run_rehearsal(
        mode=RehearsalMode.DRY_RUN,
        stores=stores if stores is not None else _memory_stores(),
        bot=bot if bot is not None else cast(TelegramTextBot, FakeBot()),
        public=ScriptedPublic(DRY_RUN_START, DRY_RUN_SYMBOL, DRY_RUN_PRICE),
        clock=clock,
        out=out,
        settings=settings,
        parameter_set=load_parameter_set("trend-pullback", "baseline-v5"),
        constraints=FixedConstraints(DRY_RUN_SYMBOL, DRY_RUN_START - timedelta(hours=1)),
        sleep=clock.sleep,
        environ={} if environ is None else environ,
        press=_dry_run_press(clock, CHAT_ID),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shadow_rehearsal",
        description="Test-only rehearsal of the SHADOW chain with one labelled test signal.",
    )
    parser.add_argument("--dry-run", action="store_true", help="drive the chain over fakes")
    parser.add_argument("--out", required=True, help="path of the evidence file to write")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: ShadowRuntimeStores | None = None,
    bot: TelegramTextBot | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_REFUSED if exc.code else EXIT_OK
    if not args.dry_run:
        print("refused: choose --dry-run", file=sys.stderr)
        return EXIT_REFUSED
    try:
        result = asyncio.run(run_dry_rehearsal(Path(args.out), stores=stores, bot=bot, environ=env))
    except RehearsalError as exc:
        print(f"rehearsal failed: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(result.path)
    return EXIT_OK if result.complete else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
