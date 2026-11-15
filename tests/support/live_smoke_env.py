"""The Demo smoke's fake environment: the composed process on the Binance-semantics fake (24-29).

TEST_ONLY: every id, price, time and trade row below is a made-up value. The process is the REAL
`build_wiring` composition (tests/support/live_composed_rig.py); the edges that are fakes are the
database (in-memory stores), the exchange orders and prices (the Binance-semantics fake), the
websocket (the supervisor is put in LIVE by hand), the Telegram application and bot, the clock and
the owner's presses. `scripts/demo_rehearsal.py` imports `build_fake_smoke_env` lazily for the
default (no `--execute`) run; a run that uses it is labelled SYNTHETIC in the evidence.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from scripts.demo_rehearsal import SmokeEnv
from src.adapters.binance_usdm import UserTradeRow
from src.adapters.binance_userdata_supervisor import StreamState
from src.live.startup import AlembicRevisions
from src.live.wiring import (
    TASK_COMMISSION,
    TASK_CONFIRM_SWEEP,
    TASK_DAY_RISK,
    TASK_MARKS,
    TASK_PROTECTION,
    TASK_RECONCILE,
    TASK_RESERVATION_SWEEP,
    TASK_SIGNAL_PUMP,
)

from tests.support.live_composed_rig import TEST_ONLY_MARK, ComposedRig, make_composed_rig
from tests.support.userdata_frames import order_trade_update_frame

D = Decimal
_TICK_TASKS = (
    TASK_MARKS,
    TASK_COMMISSION,
    TASK_CONFIRM_SWEEP,
    TASK_DAY_RISK,
    TASK_SIGNAL_PUMP,
    TASK_PROTECTION,
    TASK_RECONCILE,
    TASK_RESERVATION_SWEEP,
)
TEST_ONLY_FILL_ORDER_ID = 8_000_000_901
_USER_ID = 7001


@dataclass
class FakeSmokeEnv(SmokeEnv):
    """The smoke env plus the fake exchange and the rig, for the assertions of a test."""

    fake: Any = None
    rig: ComposedRig | None = None
    # Plan 25-02: the test-only fault objects the rig was built with (None: no fault injection).
    faults: Any = None
    sdk_faults: Any = None
    store_faults: Any = None


class FakeOwner:
    """The owner's presses as the runner's own handlers would receive them (SYNTHETIC)."""

    def __init__(self, holder: list[ComposedRig]) -> None:
        self._holder = holder
        self._n = 0

    @property
    def rig(self) -> ComposedRig:
        return _synced(self._holder[-1])

    def _update(self) -> Any:
        from tests.shadow_fakes import CHAT_ID, USER_ID

        self._n += 1
        return SimpleNamespace(
            update_id=10_000 + self._n,
            effective_chat=SimpleNamespace(id=CHAT_ID, type="private"),
            effective_user=SimpleNamespace(id=USER_ID),
        )

    async def act(self, action: str, **context: Any) -> None:
        rig = self.rig
        short_id = str(context.get("short_id", ""))
        self._n += 1
        query = f"q-{action}-{self._n}"
        if action in ("approve", "replay_approve"):
            await rig.press("APR", short_id, query_id=query)
        elif action in ("confirm", "confirm_refused", "replay_confirm"):
            if action in ("confirm", "confirm_refused"):
                await rig.clock.advance(30)
                _set_prices(rig)
            await rig.press("CNF", short_id, query_id=query)
            # The placement is a task of the process; let it finish at THIS virtual instant so
            # the virtual clock never runs ahead of a placement waiting on an executor thread.
            assert rig.wiring is not None
            await rig.wiring.service.drain()
        elif action == "safemode_exit":
            assert rig.wiring is not None
            operator = rig.wiring.operator
            await operator.safemode_exit(self._update(), SimpleNamespace(args=[]))
            reply = rig.bot.sent[-1].text
            token = reply.rsplit("/confirm ", 1)[1].split()[0]
            await operator.confirm(self._update(), SimpleNamespace(args=[token]))
        else:
            raise ValueError(f"unknown owner action {action!r}")


def _set_prices(rig: ComposedRig) -> None:
    """TEST_ONLY: stamp the fake's prices with the clock itself, so a placement task that runs
    after the next virtual second still finds a fresh reading (the executor threads make the
    interleaving of the loop tasks vary from run to run)."""
    now = rig.clock.now()
    rig.fake.now_utc = now
    rig.fake.set_mark_price("BTCUSDT", TEST_ONLY_MARK, now)
    rig.fake.set_last_price("BTCUSDT", TEST_ONLY_MARK, now)


def _synced(rig: ComposedRig) -> ComposedRig:
    """The rig's `wiring` field follows the assembly once the start sequence completed it."""
    if rig.wiring is None and rig.assembly.is_complete:
        rig.wiring = rig.assembly.wiring
    return rig


def _env_ports(rig: ComposedRig) -> Any:
    async def go_live() -> None:
        _synced(rig)
        assert rig.wiring is not None
        supervisor = rig.wiring.stream.supervisor
        now = rig.clock.now()
        supervisor._state = StreamState.LIVE
        supervisor._state_since = now
        supervisor._last_ping_at = now
        supervisor._last_pong_at = now

    async def no_task() -> None:
        return None

    def transform(ports: Any) -> Any:
        return dataclasses.replace(
            ports,
            alembic_revisions=lambda: AlembicRevisions(current="test-head", head="test-head"),
            start_stream=go_live,
            start_scheduler=no_task,
        )

    return transform


def build_fake_smoke_env(
    tmp_path: Path,
    *,
    scripted_trade: bool = True,
    drop_snapshots_before_restart: bool = False,
    faults: Any = None,
    sdk_faults: Any = None,
    store_faults: Any = None,
) -> Any:
    """A `SmokeEnv` over the composed rig; `restart` builds a second wiring over the same stores.

    Plan 25-02 (test-only, D-08): `faults`, `sdk_faults` and `store_faults` are installed in the
    first rig and in the restart rig; the restart reuses the first rig's (already wrapped) stores,
    so a store fault armed before the restart still applies after it.

    Since plan 24-37 (F3, D095) the placement itself records the verified plan constraint snapshot,
    so a restart needs no help from this env (the TEST_ONLY gap fill of plan 24-29 is gone).
    `drop_snapshots_before_restart=True` empties the in-memory snapshot store just before the
    restart: the recovery must then fail closed (SAFE_MODE DB_FAILURE), the way a database that
    lost the row would.
    """
    holder: list[ComposedRig] = []
    first = make_composed_rig(
        tmp_path, faults=faults, sdk_faults=sdk_faults, store_faults=store_faults
    )
    holder.append(first)
    owner = FakeOwner(holder)

    async def tick() -> None:
        rig = _synced(holder[-1])
        _set_prices(rig)
        wiring = rig.wiring
        if wiring is not None:
            supervisor = wiring.stream.supervisor
            if supervisor.state is StreamState.LIVE:
                now = rig.clock.now()
                supervisor._last_ping_at = now
                supervisor._last_pong_at = now
            await wiring.service.drain()
            specs = {spec.name: spec for spec in wiring.specs}
            for name in _TICK_TASKS:
                await specs[name].run()
        await rig.clock.advance(1)

    async def pause(seconds: float) -> None:
        await holder[-1].clock.advance(seconds)

    async def deliver_fill(request: Any) -> None:
        rig = holder[-1]
        (placement,) = rig.fake.calls_to("place_entry")
        quantity = placement["kwargs"]["quantity"]
        rig.fake.fill(request.entry_client_id, quantity=quantity)
        if scripted_trade:
            now = rig.clock.now()
            rig.day_reader.trades["BTCUSDT"] = (
                UserTradeRow(
                    symbol="BTCUSDT",
                    order_id=TEST_ONLY_FILL_ORDER_ID,
                    trade_id=902,
                    realized_pnl=D("0"),
                    commission=D("0.02"),
                    commission_asset="USDT",
                    margin_asset="USDT",
                    time_utc=now - timedelta(seconds=1),
                ),
            )
        frame = order_trade_update_frame(
            c=request.entry_client_id,
            i=TEST_ONLY_FILL_ORDER_ID,
            t=902,
            l=str(quantity),
            z=str(quantity),
        )
        routed = rig.route(frame)
        assert routed.fills == 1

    def placements() -> int:
        return len(holder[-1].fake.calls_to("place_entry"))

    async def restart() -> Any:
        previous = holder[-1]
        if drop_snapshots_before_restart:
            previous.stores.snapshots._rows.clear()
        second = make_composed_rig(
            tmp_path,
            stores=(previous.stores, previous.memory),
            clock=previous.clock,
            fake=previous.fake,
            session_id="composed-rig-2",
            faults=faults,
            sdk_faults=sdk_faults,
            store_faults=store_faults,  # `wrap` is idempotent over the already wrapped stores
        )
        holder.append(second)
        return make_env(second, initialize=False, restartable=False)

    def make_env(rig: ComposedRig, *, initialize: bool, restartable: bool) -> Any:
        return FakeSmokeEnv(
            fake=rig.fake,
            rig=rig,
            faults=faults,
            sdk_faults=sdk_faults,
            store_faults=store_faults,
            assembly=rig.assembly,
            clock=rig.clock.now,
            tick=tick,
            pause=pause,
            owner=owner,
            synthetic=True,
            wait_ticks=60,
            ports_transform=_env_ports(rig),
            deliver_fill=deliver_fill,
            placements=placements,
            restart=restart if restartable else None,
            initialize_gate_state=initialize,
        )

    original_positions = first.fake.snapshot_positions

    async def positions_with_liquidation(**kwargs: Any) -> Any:
        rows = await original_positions(**kwargs)
        # TEST_ONLY: a liquidation price at half the entry price, far from the stop (the B6 check
        # needs a price; the fake exchange has none).
        return [dataclasses.replace(row, liquidation_price=row.entry_price / 2) for row in rows]

    first.fake.snapshot_positions = positions_with_liquidation  # type: ignore[method-assign]
    first.set_prices()
    return make_env(first, initialize=True, restartable=True)


__all__ = ["FakeOwner", "build_fake_smoke_env"]
