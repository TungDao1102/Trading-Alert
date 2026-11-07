"""The owner-run Demo env factory and its fixtures (plan 25-09, D-04, D-08, OPS-02).

TEST_ONLY: nothing here talks to Binance, Telegram or PostgreSQL. `build_wiring` and
`make_sync_engine` are stubbed in `tests.support.demo_scenarios.demo_env`, every environment value
is a sentinel, and the SDK factory is exercised only through its Demo-host refusal or a stub that
replaces the Demo-guarded factory. What is pinned:

* the factory hands `build_wiring` the PRODUCTION constants and only the three test seams
  (`exchange_edge`, `sdk_factory`, `stores`), the Demo-guarded SDK factory underneath;
* it refuses before any build unless the Demo run is admitted and a database URL is set, naming
  variables and never values;
* presses go through the runner's own handler with the authorized chat and user ids;
* `abandon()` models a crash: the scheduler is cancelled and the stream stopped with the listenKey
  kept, with no drain and no `shutdown_in_order`.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import demo_rehearsal as dr
from src.adapters.binance_client import Environment, SdkClientBundle
from src.domain.registry import load_parameter_set
from src.live.runtime import (
    BINANCE_LIMITS_RELATIVE,
    DEMO_SYMBOLS,
    PARAMETER_SET_ID,
    REPO_ROOT,
    STRATEGY_ID,
)
from src.live.wiring import LiveStoreSet
from src.ops import redaction

from tests.support.demo_guard import DemoRunRefused
from tests.support.demo_scenarios import demo_env
from tests.support.demo_scenarios.demo_env import (
    ProgrammaticOwner,
    ProgrammaticOwnerError,
    abandon,
    build_demo_scenario_env,
)
from tests.support.demo_scenarios.harness import EnvOptions, ScenarioRecorder
from tests.support.fault_edge import FaultEdge, SdkFaults, StoreFaults
from tests.support.live_rig import forbid_real_sleep

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
SENTINELS = {
    "BINANCE_DEMO_API_KEY": "FAKE-DEMO-KEY-SENTINEL-0901",
    "BINANCE_DEMO_API_SECRET": "FAKE-DEMO-SECRET-SENTINEL-0902",
    "TELEGRAM_LIVE_BOT_TOKEN": "999999:FAKE-BOT-TOKEN-SENTINEL-0903",
    "DATABASE_URL_SYNC": "postgresql+psycopg://trader:FAKE-DB-PASSWORD-SENTINEL-0904@db.invalid/x",
    "BINANCE_LIVE_API_KEY": "FAKE-LIVE-KEY-SENTINEL-0905",
}
CHAT_ID = 424242
USER_IDS = "900,424242"
ENGINE = object()


@pytest.fixture(autouse=True)
def real_sleep_calls(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    return forbid_real_sleep(monkeypatch)


@pytest.fixture(autouse=True)
def _clean_redaction() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


def _environ(**extra: str) -> dict[str, str]:
    environ = {
        "TRADING_DEMO_RUN": "1",
        "LIVE_RUNTIME_MODE": "DEMO",
        "BINANCE_DEMO_API_KEY": SENTINELS["BINANCE_DEMO_API_KEY"],
        "BINANCE_DEMO_API_SECRET": SENTINELS["BINANCE_DEMO_API_SECRET"],
        "TELEGRAM_LIVE_BOT_TOKEN": SENTINELS["TELEGRAM_LIVE_BOT_TOKEN"],
        "TELEGRAM_LIVE_AUTHORIZED_CHAT_ID": str(CHAT_ID),
        "TELEGRAM_AUTHORIZED_USER_IDS": USER_IDS,
        "DATABASE_URL_SYNC": SENTINELS["DATABASE_URL_SYNC"],
    }
    environ.update(extra)
    return environ


def _recorder() -> ScenarioRecorder:
    return ScenarioRecorder("S01", mode=dr.RunMode.DRY_RUN, clock=lambda: NOW)


class _Stubs:
    """`build_wiring` and `make_sync_engine` of demo_env, replaced; nothing connects."""

    def __init__(self) -> None:
        self.builds: list[dict[str, Any]] = []
        self.engines: list[str] = []
        self.assemblies: list[SimpleNamespace] = []
        self.handled: list[Any] = []
        self.drained = 0
        self.operator_calls: list[tuple[str, Any]] = []

    def make_engine(self, url: str) -> object:
        self.engines.append(url)
        return ENGINE

    def build_wiring(self, **kwargs: Any) -> SimpleNamespace:
        self.builds.append(kwargs)

        async def handler(update: Any, context: Any) -> str:
            self.handled.append(update)
            return "handled"

        async def drain() -> None:
            self.drained += 1

        async def safemode_exit(update: Any, context: Any = None) -> None:
            self.operator_calls.append(("safemode_exit", update))
            await kwargs["bot"].send_message(
                chat_id=CHAT_ID, text="Leave SAFE_MODE? Within 120 s send: /confirm tok-123"
            )

        async def confirm(update: Any, context: Any = None) -> None:
            self.operator_calls.append(("confirm", list(context.args)))

        wiring = SimpleNamespace(
            runner=SimpleNamespace(handler=handler),
            service=SimpleNamespace(drain=drain),
            operator=SimpleNamespace(safemode_exit=safemode_exit, confirm=confirm),
        )
        assembly = SimpleNamespace(
            wiring=wiring, is_complete=True, bot=kwargs["bot"], scheduler_task=None
        )
        self.assemblies.append(assembly)
        return assembly


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> _Stubs:
    stubs = _Stubs()
    monkeypatch.setattr(demo_env, "build_wiring", stubs.build_wiring)
    monkeypatch.setattr(demo_env, "make_sync_engine", stubs.make_engine)
    return stubs


def _build(environ: dict[str, str] | None = None, **options: Any) -> demo_env.DemoScenarioEnv:
    return build_demo_scenario_env(
        _recorder(),
        EnvOptions(**options),
        environ=_environ() if environ is None else environ,
        clock=lambda: NOW,
        sleep=_instant_sleep,
    )


async def _instant_sleep(seconds: float) -> None:
    del seconds


# --------------------------------------------------------------------------- #
# Assembly: the production path with only the test seams added.
# --------------------------------------------------------------------------- #


def test_the_factory_builds_the_production_assembly_through_the_three_seams(
    stubs: _Stubs,
) -> None:
    faults, sdk_faults, store_faults = FaultEdge(), SdkFaults(), StoreFaults()
    env = _build(faults=faults, sdk_faults=sdk_faults, store_faults=store_faults)

    (kwargs,) = stubs.builds
    assert kwargs["symbols"] == DEMO_SYMBOLS
    assert kwargs["repo_root"] == REPO_ROOT
    expected = load_parameter_set(STRATEGY_ID, PARAMETER_SET_ID)
    assert kwargs["parameter_set"].parameter_set_hash == expected.parameter_set_hash
    assert kwargs["binance_limits"] is not None
    assert kwargs["config"].mode is Environment.DEMO
    assert kwargs["execution_limits"] is kwargs["config"].limits
    assert kwargs["engine"] is ENGINE
    assert stubs.engines == [SENTINELS["DATABASE_URL_SYNC"]]
    assert kwargs["exchange_edge"] == faults.install
    stores = kwargs["stores"]
    assert isinstance(stores, LiveStoreSet)
    assert store_faults.wrap(stores) is stores, "the stores are the ones StoreFaults wrapped"
    assert callable(kwargs["application_factory"])
    assert kwargs["session_id"] == "20261107T120000Z"
    assert env.synthetic is False and env.label == dr.EVIDENCE_KIND_DEMO
    assert env.faults is faults and env.sdk_faults is sdk_faults
    assert env.store_faults is store_faults


def test_omitted_fault_objects_are_created_fresh(stubs: _Stubs) -> None:
    env = _build()
    assert isinstance(env.faults, FaultEdge)
    assert isinstance(env.sdk_faults, SdkFaults)
    assert isinstance(env.store_faults, StoreFaults)
    assert stubs.builds[0]["exchange_edge"] == env.faults.install


def test_the_sdk_factory_is_the_demo_guarded_one_under_the_sdk_fault_proxy(
    stubs: _Stubs, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ReadOnlyClient:
        """The real SDK client has a read-only `rest_api` property; so does this stand-in."""

        def __init__(self) -> None:
            self._rest = SimpleNamespace(
                configuration=SimpleNamespace(base_path=dr.DEMO_BASE_URL),
                ping=lambda: "pong",
            )

        @property
        def rest_api(self) -> Any:
            return self._rest

    seen: list[dict[str, Any]] = []
    client = ReadOnlyClient()

    def guarded(**kwargs: Any) -> SdkClientBundle:
        seen.append(kwargs)
        return SdkClientBundle(
            environment=Environment.DEMO,
            surfaces=frozenset(),
            client=client,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(dr, "demo_guarded_sdk_factory", guarded)
    sdk_faults = SdkFaults()
    _build(sdk_faults=sdk_faults)
    factory = stubs.builds[0]["sdk_factory"]

    bundle = factory(environment=Environment.DEMO, marker="x")
    assert seen == [{"environment": Environment.DEMO, "marker": "x"}]
    assert bundle.environment is Environment.DEMO
    assert bundle.client.rest_api.ping() == "pong"
    assert bundle.client.rest_api.configuration.base_path == dr.DEMO_BASE_URL
    sdk_faults.fail_sdk("ping", RuntimeError("injected"))
    with pytest.raises(RuntimeError, match="injected"):
        bundle.client.rest_api.ping()
    assert [i.method for i in sdk_faults.injections] == ["ping"]
    assert client.rest_api.ping() == "pong", "the real client object is left untouched"


def test_the_sdk_factory_refuses_a_live_environment_through_the_real_guard(
    stubs: _Stubs,
) -> None:
    _build()
    factory = stubs.builds[0]["sdk_factory"]
    with pytest.raises(dr.DemoHostViolation):
        factory(environment=Environment.LIVE)


def test_production_constants_are_imported_not_retyped() -> None:
    text = Path(demo_env.__file__).read_text(encoding="utf-8")
    for name in (
        "STRATEGY_ID",
        "PARAMETER_SET_ID",
        "DEMO_SYMBOLS",
        "BINANCE_LIMITS_RELATIVE",
        "DATABASE_URL_VARIABLES",
        "REPO_ROOT",
        "demo_guarded_sdk_factory",
    ):
        assert name in text
    assert "'baseline-v5'" not in text and '"baseline-v5"' not in text
    assert str(BINANCE_LIMITS_RELATIVE) not in text


def test_the_clock_offset_shifts_the_process_clock(stubs: _Stubs) -> None:
    env = _build(clock_offset=timedelta(milliseconds=540))
    assert env.clock() == NOW + timedelta(milliseconds=540)
    assert stubs.builds[0]["clock"]() == NOW + timedelta(milliseconds=540)


async def test_tick_and_pause_use_the_injected_sleep(stubs: _Stubs) -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    env = build_demo_scenario_env(
        _recorder(), EnvOptions(), environ=_environ(), clock=lambda: NOW, sleep=sleep
    )
    await env.tick()
    await env.pause(1.5)
    assert slept == [dr.SMOKE_POLL_SECONDS, 1.5]
    assert env.wait_ticks == dr.DEFAULT_APPROVAL_TIMEOUT_SECONDS // dr.SMOKE_POLL_SECONDS
    assert stubs.builds[0]["sleep"] is sleep


# --------------------------------------------------------------------------- #
# Refusals come before any build or connection.
# --------------------------------------------------------------------------- #


def _refused(environ: dict[str, str], stubs: _Stubs) -> str:
    with pytest.raises(DemoRunRefused) as raised:
        _build(environ)
    assert stubs.builds == [] and stubs.engines == [], "nothing is built after a refusal"
    message = str(raised.value)
    for sentinel in SENTINELS.values():
        assert sentinel not in message, "a refusal names variables, never values"
    return message


def test_a_missing_database_url_is_refused_by_name(stubs: _Stubs) -> None:
    environ = _environ()
    del environ["DATABASE_URL_SYNC"]
    message = _refused(environ, stubs)
    assert "DATABASE_URL_SYNC" in message and "DATABASE_URL" in message


def test_a_database_url_in_the_second_variable_is_accepted(stubs: _Stubs) -> None:
    environ = _environ()
    del environ["DATABASE_URL_SYNC"]
    environ["DATABASE_URL"] = SENTINELS["DATABASE_URL_SYNC"]
    _build(environ)
    assert stubs.engines == [SENTINELS["DATABASE_URL_SYNC"]]


def test_a_live_credential_name_is_refused(stubs: _Stubs) -> None:
    message = _refused(_environ(BINANCE_LIVE_API_KEY=SENTINELS["BINANCE_LIVE_API_KEY"]), stubs)
    assert "BINANCE_LIVE_API_KEY" in message


def test_an_unset_run_variable_is_refused(stubs: _Stubs) -> None:
    environ = _environ()
    del environ["TRADING_DEMO_RUN"]
    assert "TRADING_DEMO_RUN" in _refused(environ, stubs)


def test_a_live_mode_is_refused(stubs: _Stubs) -> None:
    assert _refused(_environ(LIVE_RUNTIME_MODE="LIVE"), stubs)


def test_an_xdist_worker_is_refused(stubs: _Stubs) -> None:
    assert "PYTEST_XDIST_WORKER" in _refused(_environ(PYTEST_XDIST_WORKER="gw0"), stubs)


def test_an_unknown_owner_kind_is_refused(stubs: _Stubs) -> None:
    assert "TRADING_DEMO_OWNER" in _refused(_environ(TRADING_DEMO_OWNER="robot"), stubs)


# --------------------------------------------------------------------------- #
# The owner: presses through the runner's handler with the admitted identity.
# --------------------------------------------------------------------------- #


async def test_an_approve_press_goes_through_the_runner_handler_with_the_authorized_ids(
    stubs: _Stubs,
) -> None:
    env = _build()
    assert isinstance(env.owner, ProgrammaticOwner)
    await env.owner.act("approve", short_id="abc123")
    (update,) = stubs.handled
    assert update.callback_query.data == "APR:abc123"
    assert update.effective_chat.id == CHAT_ID
    assert update.effective_chat.type == "private"
    assert update.callback_query.message.chat_id == CHAT_ID
    assert update.callback_query.from_user.id == 900, "the smallest authorized user id"


async def test_a_replayed_approve_and_the_confirm_variants_press_the_right_prefix(
    stubs: _Stubs,
) -> None:
    env = _build()
    for action in ("replay_approve", "confirm", "confirm_refused", "replay_confirm"):
        await env.owner.act(action, short_id="abc123")
    assert [u.callback_query.data for u in stubs.handled] == [
        "APR:abc123",
        "CNF:abc123",
        "CNF:abc123",
        "CNF:abc123",
    ]
    assert stubs.drained == 3, "a confirm waits for its placement to finish"
    ids = [u.callback_query.id for u in stubs.handled]
    assert len(set(ids)) == len(ids), "every press is a distinct query"


async def test_an_unknown_action_is_refused(stubs: _Stubs) -> None:
    env = _build()
    with pytest.raises(ValueError, match="unknown owner action"):
        await env.owner.act("shrug", short_id="x")
    assert stubs.handled == []


async def test_safemode_exit_reads_the_token_from_the_bot_channel_and_confirms_it(
    stubs: _Stubs,
) -> None:
    env = _build()
    sent: list[tuple[Any, str]] = []

    class FakeTelegramBot:
        async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> None:
            sent.append((chat_id, text))

    stubs.builds[0]["bot"].bind(FakeTelegramBot())
    await env.owner.act("safemode_exit")
    first, second = stubs.operator_calls
    assert first[0] == "safemode_exit" and second == ("confirm", ["tok-123"])
    assert first[1].effective_user.id == 900 and first[1].effective_chat.id == CHAT_ID
    assert sent == [(CHAT_ID, "Leave SAFE_MODE? Within 120 s send: /confirm tok-123")], (
        "the reply is still forwarded to Telegram"
    )


async def test_safemode_exit_without_a_token_reply_raises_and_confirms_nothing(
    stubs: _Stubs,
) -> None:
    env = _build()

    async def silent(update: Any, context: Any = None) -> None:
        stubs.operator_calls.append(("safemode_exit", update))

    stubs.assemblies[0].wiring.operator.safemode_exit = silent
    with pytest.raises(ProgrammaticOwnerError, match="token"):
        await env.owner.act("safemode_exit")
    assert [call[0] for call in stubs.operator_calls] == ["safemode_exit"]


async def test_the_recording_bot_keeps_the_reply_even_when_the_send_fails(stubs: _Stubs) -> None:
    env = _build()
    with pytest.raises(Exception, match="not bound"):
        await env.owner.act("safemode_exit")
    # the unbound proxy refused the send, but the operator's reply text was captured first
    assert stubs.builds[0]["bot"].sent[-1][1].endswith("/confirm tok-123")


async def test_console_owner_is_chosen_by_the_environment(stubs: _Stubs) -> None:
    env = _build(_environ(TRADING_DEMO_OWNER="console"))
    assert isinstance(env.owner, dr.ConsoleOwner)
    assert stubs.handled == []


async def test_the_console_owner_forwards_its_instruction_to_the_owner_chat(
    stubs: _Stubs, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _build(_environ(TRADING_DEMO_OWNER="console"))
    sent: list[tuple[Any, str]] = []

    class FakeTelegramBot:
        async def send_message(self, *, chat_id: Any, text: str, reply_markup: Any = None) -> None:
            sent.append((chat_id, text))

    stubs.builds[0]["bot"].bind(FakeTelegramBot())
    await env.owner.act("approve", short_id="abc123", note="")
    assert sent and sent[0][0] == CHAT_ID and sent[0][1].startswith("REHEARSAL: ")
    assert "OPERATOR: " in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Restart and crash cut.
# --------------------------------------------------------------------------- #


async def test_a_restart_builds_a_second_process_over_the_same_engine_and_stores(
    stubs: _Stubs,
) -> None:
    faults = FaultEdge()
    env = _build(faults=faults)
    assert env.restart is not None
    second = await env.restart()
    first_kwargs, second_kwargs = stubs.builds
    assert stubs.engines == [SENTINELS["DATABASE_URL_SYNC"]], "one engine for both processes"
    assert second_kwargs["engine"] is first_kwargs["engine"]
    assert second_kwargs["stores"] is first_kwargs["stores"]
    assert second_kwargs["exchange_edge"] == faults.install == first_kwargs["exchange_edge"]
    assert second_kwargs["session_id"] != first_kwargs["session_id"], "a session id is never reused"
    assert env.initialize_gate_state is False and second.initialize_gate_state is False
    assert second.synthetic is False and second.faults is faults
    await second.owner.act("approve", short_id="s1")
    assert len(stubs.handled) == 1, "the owner of the second process presses on its own wiring"
    assert second.assembly is stubs.assemblies[1]


async def test_the_gate_state_is_initialized_only_when_asked(stubs: _Stubs) -> None:
    env = build_demo_scenario_env(
        _recorder(),
        EnvOptions(),
        environ=_environ(),
        clock=lambda: NOW,
        sleep=_instant_sleep,
        initialize_gate_state=True,
    )
    assert env.initialize_gate_state is True
    second = await env.restart()  # type: ignore[misc]
    assert second.initialize_gate_state is False, "a restart never re-initializes"


def _crash_assembly(calls: list[str], *, task: asyncio.Task[Any] | None) -> SimpleNamespace:
    async def stop(*, close_listen_key: bool) -> None:
        calls.append(f"supervisor.stop(close_listen_key={close_listen_key})")

    async def runner_stop() -> None:
        calls.append("runner.stop")

    async def forbidden_drain() -> None:
        calls.append("service.drain")
        raise AssertionError("a crash cut never drains")

    wiring = SimpleNamespace(
        stream=SimpleNamespace(supervisor=SimpleNamespace(stop=stop)),
        runner=SimpleNamespace(stop=runner_stop),
        service=SimpleNamespace(drain=forbidden_drain),
        persistence=SimpleNamespace(drain=forbidden_drain),
        scheduler=SimpleNamespace(stop=lambda: calls.append("scheduler.stop")),
    )
    return SimpleNamespace(wiring=wiring, is_complete=True, scheduler_task=task)


async def test_abandon_cancels_the_scheduler_and_keeps_the_listen_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.live import runtime

    async def forbidden_shutdown(assembly: Any) -> list[str]:
        raise AssertionError("a crash cut never runs shutdown_in_order")

    monkeypatch.setattr(runtime, "shutdown_in_order", forbidden_shutdown)
    never = asyncio.Event()
    task = asyncio.ensure_future(never.wait())
    calls: list[str] = []
    assembly = _crash_assembly(calls, task=task)

    await abandon(assembly)

    assert task.cancelled()
    assert "supervisor.stop(close_listen_key=False)" in calls
    assert "service.drain" not in calls
    assert not any(call.startswith("scheduler.stop") for call in calls)


async def test_abandon_without_a_scheduler_task_still_stops_the_stream() -> None:
    calls: list[str] = []
    await abandon(_crash_assembly(calls, task=None))
    assert calls[0] == "supervisor.stop(close_listen_key=False)"


async def test_abandon_on_an_assembly_that_never_completed_is_a_no_op() -> None:
    await abandon(SimpleNamespace(is_complete=False, scheduler_task=None))


async def test_the_env_abandon_delegates_to_the_crash_cut(stubs: _Stubs) -> None:
    env = _build()
    calls: list[str] = []
    crashed = _crash_assembly(calls, task=None)
    env = dataclasses.replace(env, assembly=crashed)
    await env.abandon()
    assert calls[0] == "supervisor.stop(close_listen_key=False)"


# --------------------------------------------------------------------------- #
# The production seam is untouched: no Demo branch in src was needed.
# --------------------------------------------------------------------------- #


def test_the_env_module_declares_itself_test_only_and_owner_run() -> None:
    tree = ast.parse(Path(demo_env.__file__).read_text(encoding="utf-8"))
    docstring = ast.get_docstring(tree) or ""
    assert "TEST_ONLY" in docstring and "owner" in docstring.lower()


def test_a_callable_clock_default_reads_utc(stubs: _Stubs) -> None:
    env = build_demo_scenario_env(
        _recorder(), EnvOptions(), environ=_environ(), sleep=_instant_sleep
    )
    clock: Callable[[], datetime] = env.clock
    assert clock().tzinfo is not None
