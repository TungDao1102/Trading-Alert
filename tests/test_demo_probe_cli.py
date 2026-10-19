"""Safety gates of the live path of `scripts/demo_probe.py` (plan 18-17 Task 2).

No credential, host or LIVE option exists; `--execute` needs a terminal and the exact phrase
`DEMO PROBE <SYMBOL>`; every refusal (limits files, environment, credentials) exits 2 or 3
before any SDK client is built and before any network call. Every test patches the SDK client
factory, the SDK client constructor, `requests.Session.request`, name lookups and non-loopback
socket connects to fail if reached. The guarded port refuses every mutating method in dry-run
mode. The AST guard pins the time contract: no `float(` call, wall-clock reads only inside
`live_clock`, no direct sleep call. Credential values are synthetic TEST_ONLY strings.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import socket
import textwrap
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import binance_common.constants as sdk_constants
import pytest
import requests
from binance_common.errors import BadRequestError
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from scripts import demo_probe as dp
from src.adapters import binance_client
from src.adapters.binance_client import CREDENTIAL_SPECS, Environment, EnvironmentRow
from src.adapters.binance_probe import BinanceProbeAdapter, ProbeBanned
from src.adapters.binance_ratelimit_gate import RATE_LIMIT_PAUSE_429, RestGateRefusal
from src.adapters.binance_usdm import PositionModeResult
from src.ops import redaction

from tests.probe_fakes import MUTATING_OPERATIONS, FakeProbePort, write_probe_limits
from tests.support.ast_guards import WALL_CLOCK_CALLS

# The real SDK client factory and constructor, kept before the autouse fixture replaces them;
# only the offline construction test restores them (sockets and HTTP stay patched to fail).
_REAL_BUILD_SDK_CLIENT = binance_client.build_sdk_client
_REAL_SDK_INIT = DerivativesTradingUsdsFutures.__init__

SCRIPT_PATH = Path(dp.__file__)
REPO_ROOT = Path(__file__).resolve().parents[1]

TEST_ONLY_KEY = "TestOnlyDemoKeyNotACredential000001"
TEST_ONLY_SECRET = "TestOnlyDemoSecretNotACredential0002"

DEMO_KEY = CREDENTIAL_SPECS[Environment.DEMO].key_variable
DEMO_SECRET = CREDENTIAL_SPECS[Environment.DEMO].secret_variable
LIVE_KEY = CREDENTIAL_SPECS[Environment.LIVE].key_variable
LIVE_SECRET = CREDENTIAL_SPECS[Environment.LIVE].secret_variable
PHRASE = "DEMO PROBE BTCUSDT"


class _Reached(AssertionError):
    """Raised by every patched network, client or confirmation entry point."""


_LOOPBACK = {"127.0.0.1", "::1"}


@pytest.fixture(autouse=True)
def forbidden(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    reached: list[str] = []
    real_socket = socket.socket

    class _LoopbackOnlySocket(real_socket):  # type: ignore[misc, valid-type]
        def connect(self, address: Any) -> None:
            if not (isinstance(address, tuple) and address[0] in _LOOPBACK):
                reached.append("socket.connect")
                raise _Reached("socket connect to a network host")
            super().connect(address)

    def _request(self: Any, *args: Any, **kwargs: Any) -> Any:
        reached.append("requests")
        raise _Reached("HTTP request")

    def _factory(**kwargs: Any) -> Any:
        reached.append("build_sdk_client")
        raise _Reached("the SDK client factory was reached")

    def _constructor(self: Any, *args: Any, **kwargs: Any) -> None:
        reached.append("DerivativesTradingUsdsFutures")
        raise _Reached("an SDK client was constructed")

    def _getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        reached.append("getaddrinfo")
        raise _Reached("name lookup")

    monkeypatch.setattr(socket, "socket", _LoopbackOnlySocket)
    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    monkeypatch.setattr(requests.Session, "request", _request)
    monkeypatch.setattr(binance_client, "build_sdk_client", _factory)
    monkeypatch.setattr(DerivativesTradingUsdsFutures, "__init__", _constructor)
    return reached


@pytest.fixture(autouse=True)
def _isolated_runtime_secrets() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    yield
    redaction.clear_runtime_secrets()


@pytest.fixture
def probe_limits(tmp_path: Path) -> Path:
    return write_probe_limits(tmp_path)


def _argv(limits: Path, tmp_path: Path, *extra: str, environment: str = "DEMO") -> list[str]:
    return [
        "--environment",
        environment,
        "--probe-limits-file",
        str(limits),
        "--evidence-dir",
        str(tmp_path / "evidence"),
        *extra,
    ]


class _Reader:
    def __init__(self, typed: str | BaseException) -> None:
        self.typed = typed
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.typed, BaseException):
            raise self.typed
        return self.typed


def _execute(
    argv: list[str],
    *,
    environ: Mapping[str, str] | None = None,
    typed: str | BaseException = PHRASE,
    tty: bool = True,
) -> tuple[int, _Reader]:
    reader = _Reader(typed)
    code = dp.main(
        [*argv, "--execute"],
        environ={} if environ is None else environ,
        is_tty=lambda: tty,
        read_confirmation=reader,
        configure_output=lambda _env: None,
    )
    return code, reader


def _demo_credentials(**extra: str) -> dict[str, str]:
    return {DEMO_KEY: TEST_ONLY_KEY, DEMO_SECRET: TEST_ONLY_SECRET, **extra}


# --------------------------------------------------------------------------- #
# The parser.
# --------------------------------------------------------------------------- #

FORBIDDEN_OPTION_WORDS = ("host", "url", "key", "secret", "token", "password", "live")


def test_no_option_names_a_host_url_key_secret_token_password_or_live() -> None:
    parser = dp._build_parser()
    options = [option for action in parser._actions for option in action.option_strings]
    for expected in (
        "--environment",
        "--limits-file",
        "--probe-limits-file",
        "--evidence-dir",
        "--fixtures-dir",
        "--only",
        "--execute",
    ):
        assert expected in options
    for option in options:
        assert not any(word in option.lower() for word in FORBIDDEN_OPTION_WORDS), option


def test_the_environment_choices_are_demo_and_testnet_only() -> None:
    parser = dp._build_parser()
    (action,) = [a for a in parser._actions if "--environment" in a.option_strings]
    assert tuple(action.choices) == ("DEMO", "TESTNET")
    assert action.required is True


@pytest.mark.parametrize("value", ["LIVE", "demo", "PROD", ""])
def test_environment_live_or_unknown_is_a_usage_error(
    tmp_path: Path, probe_limits: Path, value: str, forbidden: list[str]
) -> None:
    code = dp.main(_argv(probe_limits, tmp_path, environment=value), environ={})
    assert code == dp.EXIT_REFUSED
    assert forbidden == []


def test_the_probe_limits_file_is_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = dp.main(["--environment", "DEMO"], environ={})
    assert code == dp.EXIT_REFUSED
    assert "--probe-limits-file" in capsys.readouterr().err


def test_abbreviated_options_are_refused(tmp_path: Path, probe_limits: Path) -> None:
    code = dp.main(["--env", "DEMO", "--probe-limits-file", str(probe_limits)], environ={})
    assert code == dp.EXIT_REFUSED


# --------------------------------------------------------------------------- #
# The --execute gate.
# --------------------------------------------------------------------------- #


def test_execute_without_a_terminal_is_refused_without_a_prompt(
    tmp_path: Path, probe_limits: Path, forbidden: list[str]
) -> None:
    code, reader = _execute(_argv(probe_limits, tmp_path), environ=_demo_credentials(), tty=False)
    assert code == dp.EXIT_REFUSED
    assert reader.prompts == []
    assert forbidden == []


@pytest.mark.parametrize(
    "typed",
    ["", "demo probe btcusdt", f"{PHRASE} ", "DEMO PROBE ETHUSDT", "DEMO SMOKE BTCUSDT"],
)
def test_execute_with_a_wrong_phrase_is_refused(
    tmp_path: Path, probe_limits: Path, typed: str, forbidden: list[str]
) -> None:
    code, reader = _execute(_argv(probe_limits, tmp_path), environ=_demo_credentials(), typed=typed)
    assert code == dp.EXIT_REFUSED
    assert len(reader.prompts) == 1 and PHRASE in reader.prompts[0]
    assert forbidden == []
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("error", [EOFError(), OSError()])
def test_execute_with_eof_is_refused(
    tmp_path: Path, probe_limits: Path, error: BaseException, forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(probe_limits, tmp_path), environ=_demo_credentials(), typed=error)
    assert code == dp.EXIT_REFUSED
    assert forbidden == []


def test_only_the_exact_phrase_reaches_the_sdk_client_factory(
    tmp_path: Path, probe_limits: Path, forbidden: list[str]
) -> None:
    with pytest.raises(_Reached, match="SDK client factory"):
        _execute(_argv(probe_limits, tmp_path), environ=_demo_credentials(), typed=PHRASE)
    assert forbidden == ["build_sdk_client"]


def test_the_phrase_carries_the_symbol_of_the_probe_limits_file(
    tmp_path: Path, forbidden: list[str]
) -> None:
    limits = write_probe_limits(tmp_path, symbol="ETHUSDT", name="eth.toml")
    code, _ = _execute(_argv(limits, tmp_path), environ=_demo_credentials(), typed=PHRASE)
    assert code == dp.EXIT_REFUSED
    with pytest.raises(_Reached):
        _execute(_argv(limits, tmp_path), environ=_demo_credentials(), typed="DEMO PROBE ETHUSDT")
    assert dp.required_phrase(Environment.DEMO, "ETHUSDT") == "DEMO PROBE ETHUSDT"


def test_a_dry_run_never_prompts_and_never_reaches_the_live_rig(
    tmp_path: Path, probe_limits: Path, monkeypatch: pytest.MonkeyPatch, forbidden: list[str]
) -> None:
    def _live(*args: Any, **kwargs: Any) -> Any:
        raise _Reached("build_live_rig in a dry run")

    monkeypatch.setattr(dp, "build_live_rig", _live)
    reader = _Reader(PHRASE)
    code = dp.main(
        _argv(probe_limits, tmp_path),
        environ=_demo_credentials(),
        is_tty=lambda: True,
        read_confirmation=reader,
    )
    assert code == dp.EXIT_OK
    assert reader.prompts == []
    assert forbidden == []


def test_main_passes_the_injected_clock_and_sleep_to_the_live_rig(
    tmp_path: Path, probe_limits: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def _live(config: dp.ProbeConfig, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise _Reached("stop after the live rig was asked for")

    async def _sleep(seconds: int) -> None:
        raise AssertionError("never called")

    def _clock() -> datetime:
        return datetime(2026, 10, 16, tzinfo=UTC)

    monkeypatch.setattr(dp, "build_live_rig", _live)
    with pytest.raises(_Reached):
        dp.main(
            [*_argv(probe_limits, tmp_path), "--execute"],
            environ=_demo_credentials(),
            is_tty=lambda: True,
            read_confirmation=lambda _p: PHRASE,
            configure_output=lambda _env: None,
            clock=_clock,
            sleep=_sleep,
        )
    assert seen["clock"] is _clock and seen["sleep"] is _sleep
    assert seen["environ"] == _demo_credentials()


def test_the_banner_states_the_label_the_d055_rule_the_singleton_and_the_approval(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dp.main(_argv(probe_limits, tmp_path), environ={})
    out = capsys.readouterr().out
    assert "demo-observed, not mainnet" in out
    assert "records facts and stops" in out
    assert "singleton" in out
    assert "O-18-03" in out


# --------------------------------------------------------------------------- #
# Refusals after the gate, before any SDK client: each exits 2 and names a variable only.
# --------------------------------------------------------------------------- #


def _refused(
    capsys: pytest.CaptureFixture[str],
    forbidden: list[str],
    code: int,
    *,
    names: str,
    expected_code: int = dp.EXIT_REFUSED,
) -> str:
    err = capsys.readouterr().err
    assert code == expected_code, err
    assert names in err
    assert TEST_ONLY_KEY not in err and TEST_ONLY_SECRET not in err
    assert forbidden == []
    return err


def test_missing_credential_variables_refuse(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(probe_limits, tmp_path), environ={})
    _refused(capsys, forbidden, code, names=DEMO_KEY)


def test_a_missing_secret_variable_refuses(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(probe_limits, tmp_path), environ={DEMO_KEY: TEST_ONLY_KEY})
    _refused(capsys, forbidden, code, names=DEMO_SECRET)


def test_variable_plus_file_is_ambiguous_and_refuses(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    outside = tmp_path / "key.txt"
    outside.write_text(TEST_ONLY_KEY, encoding="utf-8")
    environ = _demo_credentials(**{f"{DEMO_KEY}_FILE": str(outside)})
    code, _ = _execute(_argv(probe_limits, tmp_path), environ=environ)
    err = _refused(capsys, forbidden, code, names=f"{DEMO_KEY}_FILE")
    assert "ambiguous" in err
    assert str(outside) not in err


def test_a_credential_file_inside_the_repository_refuses(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    inside = REPO_ROOT / "pyproject.toml"
    environ = {f"{DEMO_KEY}_FILE": str(inside), DEMO_SECRET: TEST_ONLY_SECRET}
    code, _ = _execute(_argv(probe_limits, tmp_path), environ=environ)
    err = _refused(capsys, forbidden, code, names=f"{DEMO_KEY}_FILE")
    assert "inside the repository" in err


@pytest.mark.parametrize(
    "live_variable", [LIVE_KEY, LIVE_SECRET, f"{LIVE_KEY}_FILE", f"{LIVE_SECRET}_FILE"]
)
def test_any_live_credential_variable_refuses(
    tmp_path: Path,
    probe_limits: Path,
    capsys: pytest.CaptureFixture[str],
    forbidden: list[str],
    live_variable: str,
) -> None:
    environ = _demo_credentials(**{live_variable: "TestOnlyLiveValueNotACredential"})
    code, _ = _execute(_argv(probe_limits, tmp_path), environ=environ)
    err = _refused(capsys, forbidden, code, names=live_variable)
    assert "TestOnlyLiveValueNotACredential" not in err


def test_a_missing_limits_file_refuses(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    missing = tmp_path / "absent-limits.toml"
    code, reader = _execute(
        _argv(probe_limits, tmp_path, "--limits-file", str(missing)), environ=_demo_credentials()
    )
    _refused(capsys, forbidden, code, names="absent-limits.toml")
    assert reader.prompts == []


def test_an_invalid_limits_file_refuses(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    bad = tmp_path / "bad-limits.toml"
    bad.write_text("[client]\nrest_timeout_ms = 5\n", encoding="utf-8")
    code, _ = _execute(
        _argv(probe_limits, tmp_path, "--limits-file", str(bad)), environ=_demo_credentials()
    )
    _refused(capsys, forbidden, code, names="bad-limits.toml")


def test_a_missing_probe_limits_file_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, reader = _execute(
        _argv(tmp_path / "absent-probe.toml", tmp_path), environ=_demo_credentials()
    )
    _refused(capsys, forbidden, code, names="absent-probe.toml")
    assert reader.prompts == []


def _edited_limits(tmp_path: Path, old: str, new: str) -> Path:
    path = write_probe_limits(tmp_path, name="edited.toml")
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ('symbol = "BTCUSDT"', 'symbol = "btcusdt"', "order.symbol"),
        ('symbol = "BTCUSDT"', 'symbol = "BTC"', "order.symbol"),
        ('symbol = "BTCUSDT"', 'symbol = "BTCUSDTBTCUSDTBTCUSDTX"', "order.symbol"),
        ('symbol = "BTCUSDT"', 'symbol = "BTC-USDT"', "order.symbol"),
        ('quantity = "0.002"', 'quantity = "0"', "order.quantity"),
        ('quantity = "0.002"', 'quantity = "-0.002"', "order.quantity"),
        ('quantity = "0.002"', "quantity = 0.002", "order.quantity"),
        ('quantity = "0.002"', 'quantity = "1e-3"', "order.quantity"),
        ('max_notional_quote = "150"', 'max_notional_quote = "0"', "order.max_notional_quote"),
        ('max_notional_quote = "150"', "max_notional_quote = 150", "order.max_notional_quote"),
        ('far_price_fraction = "0.80"', 'far_price_fraction = "0"', "order.far_price_fraction"),
        ('far_price_fraction = "0.80"', 'far_price_fraction = "1"', "order.far_price_fraction"),
        ('far_price_fraction = "0.80"', 'far_price_fraction = "1.5"', "order.far_price_fraction"),
        ('far_price_fraction = "0.80"', 'far_price_fraction = "-0.5"', "order.far_price_fraction"),
        ("case_timeout_seconds = 30", "case_timeout_seconds = 0", "waits.case_timeout_seconds"),
        ("stream_gap = false", 'stream_gap = "no"', "optional_cases.stream_gap"),
    ],
)
def test_an_invalid_probe_limits_value_refuses_before_any_network_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    forbidden: list[str],
    old: str,
    new: str,
    key: str,
) -> None:
    limits = _edited_limits(tmp_path, old, new)
    code, reader = _execute(_argv(limits, tmp_path), environ=_demo_credentials())
    err = _refused(capsys, forbidden, code, names=key)
    assert "edited.toml" in err
    assert reader.prompts == []


def test_an_unconfigured_environment_refuses_before_the_prompt(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, reader = _execute(
        _argv(probe_limits, tmp_path, environment="TESTNET"), environ=_demo_credentials()
    )
    err = _refused(capsys, forbidden, code, names="EnvironmentNotConfigured")
    assert reader.prompts == []
    assert "TESTNET" in err


def test_a_demo_websocket_url_not_configured_refuses(
    tmp_path: Path,
    probe_limits: Path,
    capsys: pytest.CaptureFixture[str],
    forbidden: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = dict(binance_client.ENVIRONMENT_ROWS)
    demo = rows[Environment.DEMO]
    rows[Environment.DEMO] = EnvironmentRow(
        environment=Environment.DEMO, rest_url=demo.rest_url, ws_streams_url=None, ws_api_url=None
    )
    monkeypatch.setattr(binance_client, "ENVIRONMENT_ROWS", MappingProxyType(rows))
    code, _ = _execute(_argv(probe_limits, tmp_path), environ=_demo_credentials())
    err = _refused(capsys, forbidden, code, names="WS_STREAMS")
    assert "EnvironmentNotConfigured" in err


def test_an_environment_violation_while_building_aborts_with_3(
    tmp_path: Path, probe_limits: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _violating_factory(config: dp.ProbeConfig) -> dp.ProbeRig:
        raise binance_client.EndpointViolation("DEMO REST endpoint does not match its row")

    code = dp.main(
        [*_argv(probe_limits, tmp_path), "--execute"],
        environ=_demo_credentials(),
        is_tty=lambda: True,
        read_confirmation=lambda _p: PHRASE,
        rig_factory=_violating_factory,
        configure_output=lambda _env: None,
    )
    assert code == dp.EXIT_ABORTED
    assert "ABORTED before any order" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# The guarded port.
# --------------------------------------------------------------------------- #


class _ModeReader:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.calls = 0

    async def get_position_mode(self) -> PositionModeResult:
        self.calls += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        assert isinstance(self.answer, PositionModeResult)
        return self.answer


def _guarded(
    mode: str, reader: _ModeReader | None = None
) -> tuple[dp.GuardedProbePort, FakeProbePort, list[int]]:
    inner = FakeProbePort()
    guard_calls: list[int] = []
    port = dp.GuardedProbePort(
        inner,
        position_mode_reader=reader or _ModeReader(PositionModeResult(dual_side_position=False)),
        frames=dp.FrameLog(),
        guard=lambda: guard_calls.append(1),
        mode=mode,
    )
    return port, inner, guard_calls


_MUTATING_CALLS: dict[str, dict[str, Any]] = {
    "new_limit_order": {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": Decimal("0.002"),
        "price": Decimal("48000"),
        "client_order_id": "dprobe-test-1",
        "position_side": "BOTH",
        "time_in_force": "GTC",
        "reduce_only": None,
    },
    "new_market_order": {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "quantity": Decimal("0.002"),
        "client_order_id": "dprobe-test-2",
        "position_side": "BOTH",
        "reduce_only": True,
    },
    "new_conditional_order": {
        "symbol": "BTCUSDT",
        "side": "SELL",
        "order_type": "STOP_MARKET",
        "client_algo_id": "dprobe-test-3",
        "position_side": "BOTH",
        "trigger_price": Decimal("40000"),
        "working_type": "MARK_PRICE",
    },
    "cancel_order": {"symbol": "BTCUSDT", "client_order_id": "dprobe-test-4"},
    "cancel_algo_order": {"client_algo_id": "dprobe-test-5"},
    "cancel_all_open_orders": {"symbol": "BTCUSDT"},
    "cancel_all_algo_open_orders": {"symbol": "BTCUSDT"},
}


def test_the_mutating_list_of_the_guarded_port_matches_the_fakes() -> None:
    assert dp.MUTATING_OPERATIONS == MUTATING_OPERATIONS
    assert set(_MUTATING_CALLS) == set(MUTATING_OPERATIONS)


@pytest.mark.parametrize("operation", sorted(_MUTATING_CALLS))
async def test_a_dry_run_guarded_port_never_reaches_a_mutating_method(operation: str) -> None:
    port, inner, guard_calls = _guarded(dp.MODE_DRY_RUN)
    with pytest.raises(dp.MutationRefused):
        await getattr(port, operation)(**_MUTATING_CALLS[operation])
    assert inner.calls == []
    assert port.mutating_attempts == 1
    assert port.call_count == 0
    assert guard_calls == [1]


@pytest.mark.parametrize("operation", sorted(_MUTATING_CALLS))
async def test_an_execute_guarded_port_guards_then_delegates(operation: str) -> None:
    port, inner, guard_calls = _guarded(dp.MODE_EXECUTE)
    await getattr(port, operation)(**_MUTATING_CALLS[operation])
    assert inner.names() == [operation]
    assert guard_calls == [1]
    assert port.call_count == 1


async def test_reads_are_guarded_and_delegated() -> None:
    port, inner, guard_calls = _guarded(dp.MODE_DRY_RUN)
    await port.open_orders(symbol="BTCUSDT")
    await port.open_algo_orders(symbol="BTCUSDT")
    await port.positions(symbol="BTCUSDT")
    await port.user_trades(symbol="BTCUSDT")
    await port.account_balance()
    await port.mark_price(symbol="BTCUSDT")
    await port.symbol_filters(symbol="BTCUSDT")
    await port.query_order(symbol="BTCUSDT", client_order_id="x")
    await port.query_algo_order(client_algo_id="y")
    assert len(inner.calls) == 9
    assert len(guard_calls) == 9


def test_the_guarded_port_has_no_attribute_passthrough() -> None:
    assert "__getattr__" not in vars(dp.GuardedProbePort)
    assert "__getattribute__" not in vars(dp.GuardedProbePort)


async def test_a_guard_refusal_stops_the_call_before_the_inner_port() -> None:
    inner = FakeProbePort()

    def _guard() -> None:
        raise binance_client.EndpointViolation("FAKE: the row does not match")

    port = dp.GuardedProbePort(
        inner,
        position_mode_reader=_ModeReader(PositionModeResult(dual_side_position=False)),
        frames=dp.FrameLog(),
        guard=_guard,
        mode=dp.MODE_EXECUTE,
    )
    with pytest.raises(binance_client.EndpointViolation):
        await port.cancel_all_open_orders(symbol="BTCUSDT")
    assert inner.calls == []


@pytest.mark.parametrize(("dual", "text"), [(False, "false"), (True, "true")])
async def test_position_mode_is_an_observation(dual: bool, text: str) -> None:
    port, _, _ = _guarded(dp.MODE_EXECUTE, _ModeReader(PositionModeResult(dual_side_position=dual)))
    observation = await port.position_mode()
    assert observation.ok is True
    assert observation.summary == {"dual_side_position": text}


async def test_a_gate_refusal_of_the_position_mode_read_is_a_probe_ban() -> None:
    port, _, _ = _guarded(dp.MODE_EXECUTE, _ModeReader(RestGateRefusal(RATE_LIMIT_PAUSE_429, 30)))
    with pytest.raises(ProbeBanned) as caught:
        await port.position_mode()
    assert caught.value.reason == RATE_LIMIT_PAUSE_429


async def test_an_exchange_error_of_the_position_mode_read_is_data() -> None:
    port, _, _ = _guarded(dp.MODE_EXECUTE, _ModeReader(BadRequestError("FAKE", -1021)))
    observation = await port.position_mode()
    assert observation.ok is False
    assert observation.error is not None
    assert observation.error.code == -1021
    assert observation.error.http_class == "BAD_REQUEST"


async def test_drop_without_a_transport_returns_false() -> None:
    port, _, _ = _guarded(dp.MODE_EXECUTE)
    assert await port.drop_stream_transport() is False


def test_the_frame_log_slices_by_marker() -> None:
    log = dp.FrameLog()
    log.add_event({"event_type": "A"})
    marker = log.marker()
    log.add_event({"event_type": "B"})
    log.add_raw({"e": "ORDER_TRADE_UPDATE"})
    log.add_state("UNKNOWN")
    assert log.events_since(marker) == [{"event_type": "B"}]
    assert log.raw_since(marker) == [{"e": "ORDER_TRADE_UPDATE"}]
    assert log.states_since(marker) == ["UNKNOWN"]
    assert log.events_since(0) == [{"event_type": "A"}, {"event_type": "B"}]


def test_build_live_rig_assembles_offline_with_one_shared_gate(
    tmp_path: Path, probe_limits: Path, monkeypatch: pytest.MonkeyPatch, forbidden: list[str]
) -> None:
    """The real SDK client is constructed offline (no request); sockets stay patched to fail."""
    monkeypatch.setattr(DerivativesTradingUsdsFutures, "__init__", _REAL_SDK_INIT)
    config = dp.parse_config([*_argv(probe_limits, tmp_path), "--execute"])
    root = logging.getLogger()
    filters_before = list(root.filters)
    try:
        rig = dp.build_live_rig(
            config, environ=_demo_credentials(), client_factory=_REAL_BUILD_SDK_CLIENT
        )
    finally:
        for added in [f for f in root.filters if f not in filters_before]:
            root.removeFilter(added)
    assert forbidden == []
    assert rig.real is True
    assert rig.clock is dp.live_clock
    assert rig.sleep is asyncio.sleep
    port = rig.port
    assert isinstance(port, dp.GuardedProbePort)
    probe = port._adapter
    assert isinstance(probe, BinanceProbeAdapter)
    gate = probe._rest_gate
    assert gate.policy == config.limits.signed.rate_limit
    assert probe._public._rest_gate is gate
    assert port._reader._rest_gate is gate
    stream = rig.stream
    assert isinstance(stream, dp.LiveStream)
    assert stream._rest_gate is gate
    assert stream._listen_keys._inner._rest_gate is gate
    assert rig.live_calls is not None and rig.live_calls() == 0


def test_live_clock_is_aware_utc() -> None:
    moment = dp.live_clock()
    assert moment.tzinfo is not None and moment.utcoffset() == UTC.utcoffset(None)


# --------------------------------------------------------------------------- #
# Source scans.
# --------------------------------------------------------------------------- #


def _tree() -> ast.Module:
    return ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))


_ENV_FILE_TOKENS = ("dotenv", "env_file", "pydantic_settings")


def test_the_script_reads_no_environment_file() -> None:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            assert not any(t in alias.name for alias in node.names for t in _ENV_FILE_TOKENS)
        elif isinstance(node, ast.ImportFrom):
            assert not any(t in (node.module or "") for t in _ENV_FILE_TOKENS)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.strip().endswith(".env"), node.value
            assert not any(t in node.value for t in _ENV_FILE_TOKENS)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in {"open", "read_text", "read_bytes", "load_dotenv"}:
                for arg in node.args:
                    assert ".env" not in ast.unparse(arg)


def _prod_hostnames() -> set[str]:
    hosts: set[str] = set()
    for name in dir(sdk_constants):
        value = getattr(sdk_constants, name)
        if name.endswith("_PROD_URL") and isinstance(value, str) and "://" in value:
            host = urlsplit(value).hostname
            if host:
                hosts.add(host)
    return hosts


def test_the_script_contains_no_mainnet_host_literal() -> None:
    hosts = _prod_hostnames()
    assert any("fapi" in host for host in hosts), "the SDK PROD constants were not found"
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    for host in hosts:
        assert host not in source, host
    assert "binance.com" not in source


def _allowed_environment_names() -> set[str]:
    names: set[str] = set()
    for spec in CREDENTIAL_SPECS.values():
        for variable in spec.variables:
            names |= {variable, f"{variable}_FILE"}
    return names


def test_the_script_reads_no_environment_variable_but_the_credential_names() -> None:
    allowed = _allowed_environment_names()
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call):
            continue
        text = ast.unparse(node.func)
        if text in {"os.environ.get", "environ.get", "env.get", "os.getenv", "getenv"}:
            assert node.args and isinstance(node.args[0], ast.Constant), text
            assert node.args[0].value in allowed, node.args[0].value
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) in {"os.environ", "env"}:
            raise AssertionError(f"environment subscript: {ast.unparse(node)}")


def test_the_script_never_constructs_the_sdk_rest_client_itself() -> None:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            assert ast.unparse(node.func) != "DerivativesTradingUsdsFutures"


def _function(name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(_tree()) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_build_live_rig_builds_exactly_one_rest_gate_and_shares_it() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    live = ast.get_source_segment(source, _function("build_live_rig")) or ""
    assert live.count("RestRateLimitGate(") == 1
    assert source.count("RestRateLimitGate(") == 1
    for holder in (
        "BinancePublicMarketData(sdk_client=bundle.client, rest_gate=gate)",
        "rest_gate=gate,",
        "SdkListenKeyPort(bundle.client.rest_api, rest_gate=gate)",
    ):
        assert holder in live, holder
    assert "BinanceProbeAdapter(" in live and "BinanceUsdmAdapter(" in live
    calls = [
        node
        for node in ast.walk(_function("build_live_rig"))
        if isinstance(node, ast.Call)
        and ast.unparse(node.func)
        in {"BinanceProbeAdapter", "BinanceUsdmAdapter", "BinancePublicMarketData", "LiveStream"}
    ]
    assert len(calls) == 4
    for call in calls:
        gate_args = [kw for kw in call.keywords if kw.arg == "rest_gate"]
        assert len(gate_args) == 1 and ast.unparse(gate_args[0].value) == "gate", ast.unparse(call)


def test_build_live_rig_defaults_to_live_clock_and_asyncio_sleep() -> None:
    live = ast.unparse(_function("build_live_rig"))
    assert "clock if clock is not None else live_clock" in live
    assert "sleep if sleep is not None else asyncio.sleep" in live
    assert "refuse_if_present=(live_spec,)" in live


# --------------------------------------------------------------------------- #
# The AST guard of the time contract (with negative controls).
# --------------------------------------------------------------------------- #

_DIRECT_SLEEPS = {"time.sleep", "asyncio.sleep"}


def time_contract_violations(source: str) -> list[str]:
    """`float(` calls, wall-clock calls outside `live_clock`, direct sleep calls."""
    tree = ast.parse(source)
    bound: dict[str, str] = {}
    module_alias: dict[str, str] = {}  # `import time as t` -> t: time
    class_alias: dict[str, str] = {}  # `from datetime import datetime as DT` -> DT: datetime
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name in {"time", "asyncio", "datetime"}:
                    module_alias[alias.asname] = alias.name
        if isinstance(node, ast.ImportFrom) and node.module in {"time", "asyncio", "datetime"}:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                if full in WALL_CLOCK_CALLS or full in _DIRECT_SLEEPS:
                    bound[alias.asname or alias.name] = full
                if node.module == "datetime" and alias.name in {"datetime", "date"}:
                    class_alias[alias.asname or alias.name] = alias.name
    found: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def _scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _scope
        visit_AsyncFunctionDef = _scope

        def visit_Call(self, node: ast.Call) -> None:
            text = ast.unparse(node.func)
            head, _, rest = text.partition(".")
            if head in module_alias:
                text = module_alias[head] + ("." + rest if rest else "")
            elif head in class_alias and rest:
                text = class_alias[head] + "." + rest
            name = bound.get(text, text)
            if name.endswith(".time") and (
                "get_running_loop()" in name
                or "get_event_loop()" in name
                or name.split(".")[-2:] == ["loop", "time"]
            ):
                found.append(f"event-loop clock {name} at line {node.lineno}")
            if text in {"float", "builtins.float"}:
                found.append(f"float call at line {node.lineno}")
            if name in _DIRECT_SLEEPS:
                found.append(f"direct sleep call {name} at line {node.lineno}")
            if any(name == clock or name.endswith("." + clock) for clock in WALL_CLOCK_CALLS):
                if "live_clock" not in self.stack:
                    found.append(f"wall-clock call {name} outside live_clock at {node.lineno}")
            self.generic_visit(node)

    _Visitor().visit(tree)
    return found


def test_the_script_keeps_the_time_contract() -> None:
    assert time_contract_violations(SCRIPT_PATH.read_text(encoding="utf-8")) == []


def test_the_script_reads_the_wall_clock_only_in_live_clock() -> None:
    tree = _tree()
    owners: list[str] = []
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "datetime.now":
                owners.append(function.name)
    assert owners == ["live_clock"]


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        (
            """
            from datetime import UTC, datetime

            def helper():
                return datetime.now(UTC)
            """,
            "wall-clock call datetime.now outside live_clock",
        ),
        (
            """
            import time

            def stamp():
                return time.time()
            """,
            "wall-clock call time.time outside live_clock",
        ),
        (
            """
            def ratio(text):
                return float(text)
            """,
            "float call",
        ),
        (
            """
            import time

            def pause():
                time.sleep(1)
            """,
            "direct sleep call time.sleep",
        ),
        (
            """
            import asyncio

            async def pause():
                await asyncio.sleep(1)
            """,
            "direct sleep call asyncio.sleep",
        ),
        (
            """
            from time import sleep

            def pause():
                sleep(1)
            """,
            "direct sleep call time.sleep",
        ),
        (
            """
            import time as t

            def stamp():
                return t.time()
            """,
            "wall-clock call time.time outside live_clock",
        ),
        (
            """
            from datetime import datetime as DT

            def stamp():
                return DT.now()
            """,
            "wall-clock call datetime.now outside live_clock",
        ),
        (
            """
            import asyncio as aio

            async def pause():
                await aio.sleep(1)
            """,
            "direct sleep call asyncio.sleep",
        ),
        (
            """
            import asyncio

            def stamp():
                return asyncio.get_running_loop().time()
            """,
            "event-loop clock",
        ),
    ],
)
def test_the_time_guard_flags_each_negative_control(snippet: str, expected: str) -> None:
    violations = time_contract_violations(textwrap.dedent(snippet))
    assert any(expected in violation for violation in violations), violations


def test_the_time_guard_allows_a_wall_clock_read_inside_live_clock_and_a_sleep_value() -> None:
    source = textwrap.dedent(
        """
        import asyncio
        from datetime import UTC, datetime

        def live_clock():
            return datetime.now(UTC)

        def rig(sleep=None):
            return sleep if sleep is not None else asyncio.sleep
        """
    )
    assert time_contract_violations(source) == []


def test_the_signature_of_wait_up_to_is_the_contract() -> None:
    parameters = list(inspect.signature(dp.wait_up_to).parameters)
    assert parameters == ["rig", "predicate", "timeout_seconds"]
    assert list(inspect.signature(dp.ProbeRig).parameters)[:3] == ["port", "clock", "sleep"]
    assert list(inspect.signature(dp.CaseContext).parameters) == ["rig", "config", "recorder"]
