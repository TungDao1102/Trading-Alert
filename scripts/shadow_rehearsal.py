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
and never waits; its evidence carries proof class `FAKE`. Like the live mode it refuses any
`BINANCE_` variable first (plan 16-53; the check runs before the mode branch).

`--live-telegram --i-am-the-operator` is the operator's run of plan 16-40 in the compose project
`trading-rehearsal` (its own database, RUNBOOK 20.4): the real bot of the authorized chat shows
the labelled alert, the operator presses APPROVE and CONFIRM, and the simulated position is
advanced over live public 1m minutes (no credential). It needs the explicit operator flag,
refuses any `BINANCE_` variable (only the name is printed), reads only the allowed environment
names (`src/paper/runtime_config.py`), and writes the evidence with proof class
`REAL_REHEARSAL`. It must never be started by an automated task.

Exit codes::

    0  the run completed: the position opened and the label was seen (evidence written)
    1  the run ended without an opened position, or failed (evidence written when possible)
    2  refused before any work (usage, or --live-telegram without --i-am-the-operator)
    3  refused: a trade-capable (BINANCE_*) environment variable is present (both modes)
    4  refused: the rehearsal already ran on this database (REV-03: once); nothing was written
    5  refused: the live environment or the ratified configuration is incomplete (names only)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
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
from src.domain.registry import ParameterSet, load_parameter_set  # noqa: E402
from src.domain.signal import Signal  # noqa: E402
from src.domain.trade_plan import TradePlan  # noqa: E402
from src.ops.redaction import configure_logging  # noqa: E402
from src.paper.rehearsal import (  # noqa: E402
    PressFn,
    RehearsalAlreadyRan,
    RehearsalError,
    RehearsalMode,
    RehearsalResult,
    RehearsalSettings,
    run_rehearsal,
)
from src.paper.runtime_config import (  # noqa: E402
    ConfigNotRatified,
    RuntimeConfig,
    load_runtime_config,
    parse_authorized_user_ids,
    read_env,
    refuse_trade_capable_env,
)
from src.paper.shadow_confirm import CONFIRM_TTL_SECONDS_DEFAULT  # noqa: E402
from src.paper.shadow_runtime import (  # noqa: E402
    ShadowCoordinator,
    ShadowPublicFeed,
    ShadowRuntimeStores,
    SnapshotSource,
)
from src.risk.types import ConstraintSnapshot  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_TRADE_CAPABLE = 3
EXIT_ALREADY_RAN = 4
EXIT_NOT_CONFIGURED = 5

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


def dry_run_press(
    clock: VirtualClock, chat_id: int
) -> Callable[[ShadowCoordinator, str, str], Awaitable[None]]:
    """The operator's presses of a dry run: PTB-shaped updates through the real callback path.

    Only fakes use it. A live run has no press function: the operator presses the real buttons.
    """
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
    from tests.shadow_fakes import AUTHORIZED_USER_IDS, CHAT_ID, FakeBot

    clock = VirtualClock(DRY_RUN_START)
    settings = RehearsalSettings(
        symbol=DRY_RUN_SYMBOL,
        chat_id=CHAT_ID,
        authorized_user_ids=AUTHORIZED_USER_IDS,
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
        press=dry_run_press(clock, CHAT_ID),
    )


# --------------------------------------------------------------------------- #
# Live mode (the operator's run; never started by an automated task).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LiveSetup:
    """The validated inputs of a live run (names of problems only, never values)."""

    chat_id: int
    authorized_user_ids: frozenset[int]
    token: str | None
    database_url: str | None
    config: RuntimeConfig
    parameter_set: ParameterSet


def _live_setup(
    values: Mapping[str, str], *, need_token: bool, need_database: bool
) -> LiveSetup | list[str]:
    """Read the allowed variables and the ratified configuration; the problems otherwise."""
    problems: list[str] = []
    chat_id = 0
    raw_chat = values.get("TELEGRAM_AUTHORIZED_CHAT_ID", "")
    try:
        chat_id = int(raw_chat)
    except ValueError:
        problems.append(
            "TELEGRAM_AUTHORIZED_CHAT_ID" + (" (must be an integer)" if raw_chat else "")
        )
    user_ids: frozenset[int] = frozenset()  # only used when no problem was recorded
    raw_users = values.get("TELEGRAM_AUTHORIZED_USER_IDS", "")
    if not raw_users.strip():
        problems.append("TELEGRAM_AUTHORIZED_USER_IDS (missing)")
    else:
        try:
            user_ids = parse_authorized_user_ids(raw_users)
        except ValueError:
            problems.append(
                "TELEGRAM_AUTHORIZED_USER_IDS (must be comma-separated positive integers)"
            )
    token = values.get("TELEGRAM_BOT_TOKEN") or None
    if need_token and token is None:
        problems.append("TELEGRAM_BOT_TOKEN")
    database_url = values.get("DATABASE_URL_SYNC") or values.get("DATABASE_URL") or None
    if need_database and database_url is None:
        problems.append("DATABASE_URL_SYNC or DATABASE_URL")
    config: RuntimeConfig | None = None
    try:
        config = load_runtime_config(values.get("PAPER_RUNTIME_CONFIG"))
    except ConfigNotRatified as exc:
        problems.extend(exc.problems)
    parameter_set: ParameterSet | None = None
    strategy_id = values.get("PAPER_STRATEGY_ID")
    parameter_set_id = values.get("PAPER_PARAMETER_SET_ID")
    if not strategy_id or not parameter_set_id:
        problems.append("PAPER_STRATEGY_ID and PAPER_PARAMETER_SET_ID")
    else:
        try:
            parameter_set = load_parameter_set(strategy_id, parameter_set_id)
        except Exception as exc:  # noqa: BLE001 - only the class is reported
            problems.append(f"the parameter set cannot be loaded ({type(exc).__name__})")
    if problems or config is None or parameter_set is None:
        return problems
    return LiveSetup(chat_id, user_ids, token, database_url, config, parameter_set)


def _pg_stores(url: str) -> tuple[ShadowRuntimeStores, Callable[[], None]]:
    """The PostgreSQL stores of the rehearsal database and the call that disposes the engine."""
    from src.persistence.engine import make_sync_engine
    from src.persistence.shadow_stores import PgShadowStores
    from src.persistence.uow import OperationalDatabase

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = make_sync_engine(url)
    return cast(ShadowRuntimeStores, PgShadowStores(OperationalDatabase(engine))), engine.dispose


async def run_live_rehearsal(
    out: Path,
    *,
    setup: LiveSetup,
    symbol: str,
    wait_seconds: int,
    environ: Mapping[str, str],
    stores: ShadowRuntimeStores | None,
    bot: TelegramTextBot | None,
    public: ShadowPublicFeed | None,
    constraints: SnapshotSource | None,
    clock: Callable[[], datetime] | None,
    sleep: Callable[[float], Awaitable[None]] | None,
    press: PressFn | None,
    application_factory: Callable[[dict[str, Any]], Any] | None,
) -> RehearsalResult:
    """The rehearsal with the operator's real presses. Every port is injectable (tests)."""
    dispose: Callable[[], None] = lambda: None  # noqa: E731
    if stores is None:
        if setup.database_url is None:  # pragma: no cover - _live_setup requires it
            raise RehearsalError("no database is configured")
        stores, dispose = _pg_stores(setup.database_url)
    try:
        if public is None:
            from src.adapters.binance_public import BinancePublicMarketData

            public = cast(ShadowPublicFeed, BinancePublicMarketData())
        now = clock if clock is not None else _utc_now
        if constraints is None:
            from src.paper.market_inputs import ConstraintProvider

            provider = ConstraintProvider(
                public=cast(Any, public), symbols=setup.config.symbols, clock=now
            )
            await provider.refresh()
            constraints = provider
        if bot is None and application_factory is None:
            token = setup.token
            if token is None:  # pragma: no cover - _live_setup requires it
                raise RehearsalError("no Telegram bot token is configured")

            def build(callback_kwargs: dict[str, Any]) -> Any:
                from src.adapters.telegram_callbacks import build_application

                return build_application(token=token, **callback_kwargs)

            application_factory = build
        settings = RehearsalSettings(
            symbol=symbol,
            chat_id=setup.chat_id,
            authorized_user_ids=setup.authorized_user_ids,
            initial_equity=setup.config.account.initial_equity,
            risk_rate=setup.config.account.risk_rate,
            minute_poll_interval_seconds=setup.config.timing.minute_poll_interval_seconds,
            minute_close_lag_seconds=setup.config.timing.minute_close_lag_seconds,
            confirm_ttl_seconds=CONFIRM_TTL_SECONDS_DEFAULT,
            max_wait_seconds=wait_seconds,
        )
        return await run_rehearsal(
            mode=RehearsalMode.LIVE,
            stores=stores,
            bot=bot,
            public=public,
            clock=now,
            out=out,
            settings=settings,
            parameter_set=setup.parameter_set,
            constraints=constraints,
            sleep=sleep if sleep is not None else asyncio.sleep,
            environ=environ,
            press=press,
            application_factory=application_factory,
        )
    finally:
        dispose()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shadow_rehearsal",
        description="Test-only rehearsal of the SHADOW chain with one labelled test signal.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="drive the chain over fakes")
    mode.add_argument(
        "--live-telegram",
        action="store_true",
        help="real Telegram presses and live public minutes (operator only, plan 16-40)",
    )
    parser.add_argument(
        "--i-am-the-operator",
        action="store_true",
        help="required by --live-telegram: the operator runs it in the rehearsal project",
    )
    parser.add_argument("--out", required=True, help="path of the evidence file to write")
    parser.add_argument("--symbol", default=None, help="live symbol (default: the first in scope)")
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=RehearsalSettings.max_wait_seconds,
        help="how long a live run waits for the presses and the fill after the alert",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stores: ShadowRuntimeStores | None = None,
    bot: TelegramTextBot | None = None,
    public: ShadowPublicFeed | None = None,
    constraints: SnapshotSource | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    press: PressFn | None = None,
    application_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_REFUSED if exc.code else EXIT_OK
    out = Path(args.out)
    # Trade-capable names first, in both modes: only the NAME is ever printed.
    names = refuse_trade_capable_env(env)
    if names:
        for name in names:
            print(f"refused: trade-capable variable present: {name}", file=sys.stderr)
        return EXIT_TRADE_CAPABLE
    if args.dry_run:
        return _finish(run_dry_rehearsal(out, stores=stores, bot=bot, environ=env))
    # Live mode.
    if not args.i_am_the_operator:
        print("refused: --live-telegram needs --i-am-the-operator", file=sys.stderr)
        return EXIT_REFUSED
    values = read_env(env)
    setup = _live_setup(
        values, need_token=bot is None and application_factory is None, need_database=stores is None
    )
    if isinstance(setup, list):
        print("refused: not configured: " + ", ".join(setup), file=sys.stderr)
        return EXIT_NOT_CONFIGURED
    symbol = args.symbol if args.symbol is not None else setup.config.symbols[0]
    if symbol not in setup.config.symbols:
        print("refused: the symbol is not in the configured scope", file=sys.stderr)
        return EXIT_REFUSED
    if stores is None:
        configure_logging(env)
    return _finish(
        run_live_rehearsal(
            out,
            setup=setup,
            symbol=symbol,
            wait_seconds=args.wait_seconds,
            environ=env,
            stores=stores,
            bot=bot,
            public=public,
            constraints=constraints,
            clock=clock,
            sleep=sleep,
            press=press,
            application_factory=application_factory,
        )
    )


def _finish(run: Coroutine[Any, Any, RehearsalResult]) -> int:
    """Run the rehearsal and map its outcome to the exit code (class names only on errors)."""
    try:
        result = asyncio.run(run)
    except RehearsalAlreadyRan as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_ALREADY_RAN
    except RehearsalError as exc:
        print(f"rehearsal failed: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001 - never print a message that may carry a URL
        print(f"rehearsal failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_FAILED
    print(result.path)
    return EXIT_OK if result.complete else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
