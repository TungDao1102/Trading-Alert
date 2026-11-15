"""TEST_ONLY: the Binance Demo scenario env, owner-run on Demo only (plan 25-09, D-04, D-08).

`build_demo_scenario_env` composes the SAME live process as production: it mirrors
`src.live.runtime.default_assemble` and calls `build_wiring` with the production constants imported
from `src.live.runtime` (never re-typed), `make_sync_engine`, the PostgreSQL stores and the
Demo-guarded SDK factory. `default_assemble` passes no `exchange_edge`, so this module calls
`build_wiring` itself; the only additions are the three test seams `build_wiring` already has:
`exchange_edge` (`FaultEdge.install`), `sdk_factory` (`SdkFaults.wrap_factory` over
`demo_guarded_sdk_factory`) and `stores` (`StoreFaults.wrap`). There is no Demo branch in `src`.

Nothing here runs in an agent session or in CI: the env is built by the `make_demo_env` fixture of
`tests/demo/conftest.py`, which exists only under `pytest -m demo` with `TRADING_DEMO_RUN=1`. The
env refuses, before any network call or connection, unless `assert_demo_run_environment` admits the
environment and a database URL variable is set (names only, never values). Optional variables:

* `TRADING_DEMO_OWNER=console`  the owner taps on the real bot (Phase 24 `ConsoleOwner`); the
  default and `programmatic` press through the runner's own `on_callback` handler instead;
* `TRADING_DEMO_INITIALIZE_GATE_STATE=1`  read by the fixture: the first process of the session
  initializes the kill-gate state (the `--initialize-gate-state` of the smoke).

Presses (Pattern 3): `ProgrammaticOwner` builds a callback update with the admitted authorized chat
id and the smallest authorized user id and hands it to `wiring.runner.handler`, the handler Telegram
polling invokes. The press carries no `message_id` (the card of a real chat has an id this process
never saw), so the approval flow sends its next card as a new message. A crash cut (Pattern 4) is
`abandon()`: the scheduler task is cancelled and the stream stopped with `close_listen_key=False`,
with no drain and no `shutdown_in_order`; a second process then starts over the same database.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from scripts import demo_rehearsal as dr
from src.adapters.binance_limits import load_binance_limits
from src.domain.registry import load_parameter_set
from src.live.runtime import (
    BINANCE_LIMITS_RELATIVE,
    DATABASE_URL_VARIABLES,
    DEMO_SYMBOLS,
    PARAMETER_SET_ID,
    REPO_ROOT,
    STRATEGY_ID,
)
from src.live.wiring import build_pg_stores, build_wiring
from src.live.wiring_parts import LiveBotProxy
from src.persistence.engine import make_sync_engine
from src.persistence.uow import OperationalDatabase

from tests.shadow_fakes import make_callback_update
from tests.support.demo_guard import DemoRunRefused, assert_demo_run_environment
from tests.support.demo_scenarios.evidence_index import write_session_index
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder
from tests.support.fault_edge import FaultEdge, SdkFaults, StoreFaults

OWNER_VARIABLE = "TRADING_DEMO_OWNER"
OWNER_PROGRAMMATIC = "programmatic"
OWNER_CONSOLE = "console"
INITIALIZE_GATE_STATE_VARIABLE = "TRADING_DEMO_INITIALIZE_GATE_STATE"
EVIDENCE_DIR = REPO_ROOT / ".planning" / "phases" / "25-demo-integration-test-campaign" / "evidence"

SleepFn = Callable[[float], Awaitable[None]]


class ProgrammaticOwnerError(RuntimeError):
    """A programmatic press could not be completed (for example no confirm token was sent)."""


# --------------------------------------------------------------------------- #
# The bot: a forwarding wrapper that remembers what the process sent.
# --------------------------------------------------------------------------- #


class RecordingBot:
    """A `TelegramTextBot` that forwards to `LiveBotProxy` and remembers each outgoing text.

    The operator's reply (the `/confirm <token>` line of `/safemode_exit`) leaves the process
    through `bot.send_message`, so the programmatic owner reads the token here and never from
    Telegram history. The text is recorded before the forward: a failed send changes nothing.
    The list stays in memory; it is never written to evidence.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.sent: list[tuple[Any, str]] = []

    @property
    def is_bound(self) -> bool:
        return bool(getattr(self._inner, "is_bound", True))

    def bind(self, bot: Any) -> None:
        self._inner.bind(bot)

    async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> object:
        self.sent.append((chat_id, text))
        return await self._inner.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

    async def edit_message_text(
        self, *, chat_id: Any, message_id: int, text: str, reply_markup: Any = None
    ) -> object:
        return await self._inner.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )

    async def edit_message_reply_markup(
        self, *, chat_id: Any, message_id: int, reply_markup: Any = None
    ) -> object:
        return await self._inner.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )

    def __getattr__(self, name: str) -> Any:
        if name in ("_inner", "sent") or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)


# --------------------------------------------------------------------------- #
# The owner.
# --------------------------------------------------------------------------- #


class ProgrammaticOwner:
    """The owner's presses as the runner's own handlers receive them, on Binance Demo.

    Every action of the Phase 24 `FakeOwner`: `approve`, `replay_approve`, `confirm`,
    `confirm_refused`, `replay_confirm` and `safemode_exit`. The press carries the authorized
    chat id and the smallest authorized user id of the admitted config (T-25-22): the same chat
    and user gates a real press passes; no bypass exists in `src`.
    """

    def __init__(
        self,
        *,
        current_wiring: Callable[[], Any],
        bot: RecordingBot,
        chat_id: int,
        user_id: int,
    ) -> None:
        self._current_wiring = current_wiring
        self._bot = bot
        self._chat_id = chat_id
        self._user_id = user_id
        self._n = 0

    async def act(self, action: str, **context: Any) -> None:
        short_id = str(context.get("short_id", ""))
        self._n += 1
        query = f"q-{action}-{self._n}"
        if action in ("approve", "replay_approve"):
            await self._press("APR", short_id, query)
        elif action in ("confirm", "confirm_refused", "replay_confirm"):
            await self._press("CNF", short_id, query)
            # The placement is a task of the process; let it finish before the flow reads on.
            await self._current_wiring().service.drain()
        elif action == "safemode_exit":
            await self._safemode_exit()
        else:
            raise ValueError(f"unknown owner action {action!r}")

    async def _press(self, prefix: str, short_id: str, query_id: str) -> Any:
        update = make_callback_update(
            data=f"{prefix}:{short_id}",
            chat_id=self._chat_id,
            query_id=query_id,
            message_chat_id=self._chat_id,
            from_user_id=self._user_id,
            message_id=None,
            chat_type="private",
        )
        return await self._current_wiring().runner.handler(update, None)

    def _command_update(self) -> Any:
        self._n += 1
        return SimpleNamespace(
            update_id=20_000 + self._n,
            effective_chat=SimpleNamespace(id=self._chat_id, type="private"),
            effective_user=SimpleNamespace(id=self._user_id),
        )

    async def _safemode_exit(self) -> None:
        operator = self._current_wiring().operator
        before = len(self._bot.sent)
        await operator.safemode_exit(self._command_update(), SimpleNamespace(args=[]))
        token = _confirm_token(self._bot.sent[before:], self._chat_id)
        await operator.confirm(self._command_update(), SimpleNamespace(args=[token]))


def _confirm_token(sent: Sequence[tuple[Any, str]], chat_id: int) -> str:
    """The token of the last `/confirm <token>` line the operator sent to the owner chat."""
    for target, text in reversed(sent):
        if target == chat_id and "/confirm " in text:
            parts = text.rsplit("/confirm ", 1)[1].split()
            if parts:
                return parts[0]
    raise ProgrammaticOwnerError("the operator sent no /confirm token to the owner chat")


# --------------------------------------------------------------------------- #
# The SDK factory: the Demo-guarded one, with a settable `rest_api`.
# --------------------------------------------------------------------------- #


class _FaultableClient:
    """The SDK client with a settable `rest_api`; every other name is forwarded.

    The real `DerivativesTradingUsdsFutures.rest_api` is a read-only property, and
    `SdkFaults.wrap_factory` replaces `client.rest_api` by a fault proxy. This shim holds the
    same REST object as an instance attribute, so the fault proxy can take its place.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.rest_api = inner.rest_api

    def __getattr__(self, name: str) -> Any:
        if name == "_inner" or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)


def _faultable_demo_sdk_factory(sdk_faults: SdkFaults) -> Callable[..., Any]:
    """`demo_guarded_sdk_factory` (host re-checked after the build), then the fault proxy."""

    def guarded(**kwargs: Any) -> Any:
        bundle = dr.demo_guarded_sdk_factory(**kwargs)
        return dataclasses.replace(bundle, client=_FaultableClient(bundle.client))

    return sdk_faults.wrap_factory(guarded)


# --------------------------------------------------------------------------- #
# The env.
# --------------------------------------------------------------------------- #


@dataclass
class DemoScenarioEnv(dr.SmokeEnv):
    """`SmokeEnv` of the real process on Demo plus the fault objects and `abandon`."""

    faults: Any = None
    sdk_faults: Any = None
    store_faults: Any = None

    async def abandon(self) -> None:
        await abandon(self.assembly)


async def abandon(assembly: Any) -> None:
    """Model a crash: cancel the scheduler, stop the stream, keep the listenKey, drain nothing.

    Neither `service.drain`, the persistence drain nor `shutdown_in_order` runs, so in-flight
    work is cut where it stands. The Telegram polling task is stopped too, because a dead process
    holds no `getUpdates` and the second process must be able to poll; that is the only step
    beyond the scheduler and the stream, and it is best effort. A no-op on an assembly the start
    sequence never completed.
    """
    if not assembly.is_complete:
        return
    wiring = assembly.wiring
    task = assembly.scheduler_task
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    await wiring.stream.supervisor.stop(close_listen_key=False)
    with contextlib.suppress(Exception):
        await wiring.runner.stop()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_demo_scenario_env(
    recorder: ScenarioRecorder,
    options: EnvOptions,
    *,
    environ: Mapping[str, str],
    clock: Callable[[], datetime] | None = None,
    sleep: SleepFn | None = None,
    initialize_gate_state: bool = False,
    approval_timeout_seconds: int = dr.DEFAULT_APPROVAL_TIMEOUT_SECONDS,
) -> DemoScenarioEnv:
    """The real live process on Binance Demo with the options' fault objects at the seams.

    Raises `DemoRunRefused` (variable names only) before any build, connection or network call
    unless the Demo run is admitted, a database URL variable is set and the owner kind is known.
    `clock` defaults to UTC now; `options.clock_offset` is added to it (S09). `sleep` is the real
    `asyncio.sleep` unless a test injects one.
    """
    config = assert_demo_run_environment(environ)  # raises DemoRunRefused, names only
    url = next((environ[name] for name in DATABASE_URL_VARIABLES if environ.get(name)), None)
    if url is None:
        raise DemoRunRefused(
            f"no database URL set: set {' or '.join(DATABASE_URL_VARIABLES)} (the Demo run keeps "
            "its approvals and plans in PostgreSQL)"
        )
    owner_kind = environ.get(OWNER_VARIABLE, OWNER_PROGRAMMATIC)
    if owner_kind not in (OWNER_PROGRAMMATIC, OWNER_CONSOLE):
        raise DemoRunRefused(
            f"{OWNER_VARIABLE} must be {OWNER_PROGRAMMATIC} or {OWNER_CONSOLE} when set"
        )

    base_clock = clock if clock is not None else _utc_now
    offset = options.clock_offset

    def process_clock() -> datetime:
        return base_clock() + offset

    sleep_fn: SleepFn = sleep if sleep is not None else asyncio.sleep

    faults = options.faults if options.faults is not None else FaultEdge()
    sdk_faults = options.sdk_faults if options.sdk_faults is not None else SdkFaults()
    store_faults = options.store_faults if options.store_faults is not None else StoreFaults()

    engine = make_sync_engine(url)  # bounded waits, UTC verified, exactly as default_assemble
    stores = store_faults.wrap(build_pg_stores(OperationalDatabase(engine)))
    binance_limits = load_binance_limits(REPO_ROOT / BINANCE_LIMITS_RELATIVE)
    parameter_set = load_parameter_set(STRATEGY_ID, PARAMETER_SET_ID)
    sdk_factory = _faultable_demo_sdk_factory(sdk_faults)
    token = config.telegram_bot_token
    chat_id = config.authorized_chat_id
    user_id = min(config.authorized_user_ids)
    assemblies: list[Any] = []
    session_ids: set[str] = set()

    def application_factory() -> Any:
        from telegram.ext import ApplicationBuilder

        return ApplicationBuilder().token(token).build()

    def make(initialize: bool) -> DemoScenarioEnv:
        started = process_clock()
        session_id = started.strftime("%Y%m%dT%H%M%SZ")
        while session_id in session_ids:  # a second process in the same second keeps its own id
            started += timedelta(seconds=1)
            session_id = started.strftime("%Y%m%dT%H%M%SZ")
        session_ids.add(session_id)
        bot = RecordingBot(LiveBotProxy())
        assembly = build_wiring(
            config=config,
            execution_limits=config.limits,
            binance_limits=binance_limits,
            parameter_set=parameter_set,
            clock=process_clock,
            sleep=sleep_fn,
            sdk_factory=sdk_factory,
            application_factory=application_factory,
            bot=bot,
            engine=engine,
            repo_root=REPO_ROOT,
            symbols=DEMO_SYMBOLS,
            session_id=session_id,
            stores=stores,
            exchange_edge=faults.install,
        )
        assemblies.append(assembly)

        async def poll() -> None:
            await sleep_fn(dr.SMOKE_POLL_SECONDS)

        async def pause(seconds: float) -> None:
            await sleep_fn(seconds)

        async def notify(text: str) -> None:
            await bot.send_message(chat_id=chat_id, text=text)

        async def restart() -> DemoScenarioEnv:
            return make(False)

        owner: dr.SmokeOwner
        if owner_kind == OWNER_CONSOLE:
            owner = dr.ConsoleOwner(recorder, notify=notify)
        else:
            owner = ProgrammaticOwner(
                current_wiring=lambda: assemblies[-1].wiring,
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
            )
        return DemoScenarioEnv(
            assembly=assembly,
            clock=process_clock,
            tick=poll,
            pause=pause,
            owner=owner,
            synthetic=False,
            wait_ticks=max(1, approval_timeout_seconds // dr.SMOKE_POLL_SECONDS),
            restart=restart,
            initialize_gate_state=initialize,
            faults=faults,
            sdk_faults=sdk_faults,
            store_faults=store_faults,
        )

    return make(initialize_gate_state)


# --------------------------------------------------------------------------- #
# The evidence of an owner session.
# --------------------------------------------------------------------------- #


class SessionEvidence:
    """The recorders of one owner session, and the one index that ends it.

    `recorder(scenario_id)` is the `scenario_recorder` fixture's callable: an EXECUTE-mode
    `ScenarioRecorder` whose `write()` goes to the phase evidence directory by default and is
    remembered. `finish()` writes a recorder the test never wrote (a failed run keeps its
    evidence, outcome FAILED) and then the session index over every file of the session.
    """

    def __init__(
        self,
        evidence_dir: Path,
        *,
        environ: Mapping[str, str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.evidence_dir = evidence_dir
        self._environ = dict(environ)
        self._clock = clock if clock is not None else _utc_now
        self._started = self._clock()
        self.files: list[Path] = []
        self._recorders: list[tuple[ScenarioRecorder, list[Path]]] = []

    def recorder(self, scenario_id: str) -> ScenarioRecorder:
        written: list[Path] = []
        session = self

        class _SessionRecorder(ScenarioRecorder):
            def write(self, directory: Path | None = None) -> Path:
                path = super().write(session.evidence_dir if directory is None else directory)
                written.append(path)
                session.files.append(path)
                return path

        recorder = _SessionRecorder(
            scenario_id,
            mode=dr.RunMode.EXECUTE,
            environ=self._environ,
            clock=self._clock,
        )
        self._recorders.append((recorder, written))
        return recorder

    def finish(self) -> Path | None:
        """Write unwritten recorders, then the session index; None if nothing was written."""
        for recorder, written in self._recorders:
            if not written and recorder.steps:
                recorder.write()
        if not self.files:
            return None
        return write_session_index(
            self.evidence_dir,
            list(self.files),
            session_id=self._started.strftime("%Y%m%dT%H%M%SZ"),
            clock=self._clock,
            environ=self._environ,
        )


def initialize_gate_state_requested(environ: Mapping[str, str] | None = None) -> bool:
    """True when the owner asked the first process of the session to initialize the gate state."""
    source = os.environ if environ is None else environ
    return source.get(INITIALIZE_GATE_STATE_VARIABLE) == "1"


class GateInitializer:
    """Hands out the gate-state initialization exactly once per session.

    The start sequence refuses `initialize_gate_state` when a gate state file already exists, so
    only the first env built in a session may ask for it; every later env (and every restart)
    starts plain.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._pending = initialize_gate_state_requested(environ)

    def take(self) -> bool:
        pending, self._pending = self._pending, False
        return pending


__all__ = [
    "EVIDENCE_DIR",
    "GateInitializer",
    "DemoScenarioEnv",
    "ProgrammaticOwner",
    "ProgrammaticOwnerError",
    "RecordingBot",
    "SessionEvidence",
    "abandon",
    "build_demo_scenario_env",
    "initialize_gate_state_requested",
]
