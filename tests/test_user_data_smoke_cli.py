"""Safety gates of the live path of `scripts/user_data_smoke.py` (plan 18-16 Task 3).

No credential, host or LIVE option exists; `--execute` needs a terminal and the exact phrase;
every refusal (credentials, limits files, environment) exits 2 or 3 before any SDK client is
built and before any network call. Every test patches the SDK client factory, the SDK client
constructor, `requests.Session.request` and non-loopback socket connects to fail if reached.
Credential values here are synthetic TEST_ONLY strings, never credentials.
"""

from __future__ import annotations

import ast
import socket
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import binance_common.constants as sdk_constants
import pytest
import requests
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from scripts import user_data_smoke as uds
from src.adapters import binance_client
from src.adapters.binance_client import CREDENTIAL_SPECS, Environment, EnvironmentRow
from src.ops import redaction

SCRIPT_PATH = Path(uds.__file__)
REPO_ROOT = Path(__file__).resolve().parents[1]

TEST_ONLY_KEY = "TestOnlyDemoKeyNotACredential000001"
TEST_ONLY_SECRET = "TestOnlyDemoSecretNotACredential0002"

TEST_ONLY_SMOKE_LIMITS = """
[order]
symbol = "{symbol}"
quantity = "0.002"
far_price_fraction = "0.96"

[waits]
event_wait_seconds = 30
cleanup_timeout_seconds = 60
"""

DEMO_KEY = CREDENTIAL_SPECS[Environment.DEMO].key_variable
DEMO_SECRET = CREDENTIAL_SPECS[Environment.DEMO].secret_variable
LIVE_KEY = CREDENTIAL_SPECS[Environment.LIVE].key_variable
LIVE_SECRET = CREDENTIAL_SPECS[Environment.LIVE].secret_variable
PHRASE = "DEMO SMOKE BTCUSDT"


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
def smoke_limits(tmp_path: Path) -> Path:
    path = tmp_path / "smoke-limits.toml"
    path.write_text(TEST_ONLY_SMOKE_LIMITS.format(symbol="BTCUSDT"), encoding="utf-8")
    return path


def _argv(smoke_limits: Path, tmp_path: Path, *extra: str, environment: str = "DEMO") -> list[str]:
    return [
        "--environment",
        environment,
        "--smoke-limits-file",
        str(smoke_limits),
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
    code = uds.main(
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
    parser = uds._build_parser()
    options = [option for action in parser._actions for option in action.option_strings]
    assert "--environment" in options and "--execute" in options
    for option in options:
        assert not any(word in option.lower() for word in FORBIDDEN_OPTION_WORDS), option


def test_the_environment_choices_are_demo_and_testnet_only() -> None:
    parser = uds._build_parser()
    (action,) = [a for a in parser._actions if "--environment" in a.option_strings]
    assert tuple(action.choices) == ("DEMO", "TESTNET")
    assert action.required is True


@pytest.mark.parametrize("value", ["LIVE", "demo", "PROD", ""])
def test_environment_live_or_unknown_is_a_usage_error(
    tmp_path: Path, smoke_limits: Path, value: str, forbidden: list[str]
) -> None:
    code = uds.main(_argv(smoke_limits, tmp_path, environment=value), environ={})
    assert code == uds.EXIT_REFUSED
    assert forbidden == []


def test_the_environment_is_required(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = uds.main(["--smoke-limits-file", str(smoke_limits)], environ={})
    assert code == uds.EXIT_REFUSED
    assert "--environment" in capsys.readouterr().err


def test_abbreviated_options_are_refused(tmp_path: Path, smoke_limits: Path) -> None:
    code = uds.main(["--env", "DEMO", "--smoke-limits-file", str(smoke_limits)], environ={})
    assert code == uds.EXIT_REFUSED


# --------------------------------------------------------------------------- #
# The --execute gate.
# --------------------------------------------------------------------------- #


def test_execute_without_a_terminal_is_refused_without_a_prompt(
    tmp_path: Path, smoke_limits: Path, forbidden: list[str]
) -> None:
    code, reader = _execute(_argv(smoke_limits, tmp_path), environ=_demo_credentials(), tty=False)
    assert code == uds.EXIT_REFUSED
    assert reader.prompts == []
    assert forbidden == []


@pytest.mark.parametrize(
    "typed", ["", "demo smoke btcusdt", f"{PHRASE} ", "DEMO SMOKE ETHUSDT", "DEMO FAR BTCUSDT"]
)
def test_execute_with_a_wrong_phrase_is_refused(
    tmp_path: Path, smoke_limits: Path, typed: str, forbidden: list[str]
) -> None:
    code, reader = _execute(_argv(smoke_limits, tmp_path), environ=_demo_credentials(), typed=typed)
    assert code == uds.EXIT_REFUSED
    assert len(reader.prompts) == 1 and PHRASE in reader.prompts[0]
    assert forbidden == []


@pytest.mark.parametrize("error", [EOFError(), OSError()])
def test_execute_with_eof_is_refused(
    tmp_path: Path, smoke_limits: Path, error: BaseException, forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ=_demo_credentials(), typed=error)
    assert code == uds.EXIT_REFUSED
    assert forbidden == []


def test_only_the_exact_phrase_reaches_the_sdk_client_factory(
    tmp_path: Path, smoke_limits: Path, forbidden: list[str]
) -> None:
    with pytest.raises(_Reached, match="SDK client factory"):
        _execute(_argv(smoke_limits, tmp_path), environ=_demo_credentials(), typed=PHRASE)
    assert forbidden == ["build_sdk_client"]


def test_the_phrase_carries_the_symbol_of_the_smoke_limits_file(
    tmp_path: Path, forbidden: list[str]
) -> None:
    limits = tmp_path / "eth.toml"
    limits.write_text(TEST_ONLY_SMOKE_LIMITS.format(symbol="ETHUSDT"), encoding="utf-8")
    code, _ = _execute(_argv(limits, tmp_path), environ=_demo_credentials(), typed=PHRASE)
    assert code == uds.EXIT_REFUSED
    with pytest.raises(_Reached):
        _execute(_argv(limits, tmp_path), environ=_demo_credentials(), typed="DEMO SMOKE ETHUSDT")
    assert uds.required_phrase(Environment.DEMO, "ETHUSDT") == "DEMO SMOKE ETHUSDT"


def test_a_dry_run_never_prompts_and_never_reaches_the_live_rig(
    tmp_path: Path, smoke_limits: Path, monkeypatch: pytest.MonkeyPatch, forbidden: list[str]
) -> None:
    def _live(*args: Any, **kwargs: Any) -> Any:
        raise _Reached("build_live_rig in a dry run")

    monkeypatch.setattr(uds, "build_live_rig", _live)
    reader = _Reader(PHRASE)
    code = uds.main(
        _argv(smoke_limits, tmp_path),
        environ=_demo_credentials(),
        is_tty=lambda: True,
        read_confirmation=reader,
    )
    assert code == uds.EXIT_OK
    assert reader.prompts == []
    assert forbidden == []


# --------------------------------------------------------------------------- #
# Refusals after the gate, before any SDK client: each exits 2 and names a variable only.
# --------------------------------------------------------------------------- #


def _refused(
    capsys: pytest.CaptureFixture[str],
    forbidden: list[str],
    code: int,
    *,
    names: str,
    expected_code: int = uds.EXIT_REFUSED,
) -> str:
    err = capsys.readouterr().err
    assert code == expected_code, err
    assert names in err
    assert TEST_ONLY_KEY not in err and TEST_ONLY_SECRET not in err
    assert forbidden == []
    return err


def test_missing_credential_variables_refuse(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ={})
    _refused(capsys, forbidden, code, names=DEMO_KEY)


def test_a_missing_secret_variable_refuses(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ={DEMO_KEY: TEST_ONLY_KEY})
    _refused(capsys, forbidden, code, names=DEMO_SECRET)


def test_variable_plus_file_is_ambiguous_and_refuses(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    outside = tmp_path / "key.txt"
    outside.write_text(TEST_ONLY_KEY, encoding="utf-8")
    environ = _demo_credentials(**{f"{DEMO_KEY}_FILE": str(outside)})
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ=environ)
    err = _refused(capsys, forbidden, code, names=f"{DEMO_KEY}_FILE")
    assert "ambiguous" in err
    assert str(outside) not in err


def test_a_credential_file_inside_the_repository_refuses(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    inside = REPO_ROOT / "pyproject.toml"
    environ = {f"{DEMO_KEY}_FILE": str(inside), DEMO_SECRET: TEST_ONLY_SECRET}
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ=environ)
    err = _refused(capsys, forbidden, code, names=f"{DEMO_KEY}_FILE")
    assert "inside the repository" in err


@pytest.mark.parametrize(
    "live_variable", [LIVE_KEY, LIVE_SECRET, f"{LIVE_KEY}_FILE", f"{LIVE_SECRET}_FILE"]
)
def test_any_live_credential_variable_refuses(
    tmp_path: Path,
    smoke_limits: Path,
    capsys: pytest.CaptureFixture[str],
    forbidden: list[str],
    live_variable: str,
) -> None:
    environ = _demo_credentials(**{live_variable: "TestOnlyLiveValueNotACredential"})
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ=environ)
    err = _refused(capsys, forbidden, code, names=live_variable)
    assert "TestOnlyLiveValueNotACredential" not in err


def test_a_missing_limits_file_refuses(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    missing = tmp_path / "absent-limits.toml"
    code, reader = _execute(
        _argv(smoke_limits, tmp_path, "--limits-file", str(missing)), environ=_demo_credentials()
    )
    _refused(capsys, forbidden, code, names="absent-limits.toml")
    assert reader.prompts == []


def test_an_invalid_limits_file_refuses(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    bad = tmp_path / "bad-limits.toml"
    bad.write_text("[client]\nrest_timeout_ms = 5\n", encoding="utf-8")
    code, _ = _execute(
        _argv(smoke_limits, tmp_path, "--limits-file", str(bad)), environ=_demo_credentials()
    )
    _refused(capsys, forbidden, code, names="bad-limits.toml")


def test_a_missing_smoke_limits_file_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, _ = _execute(_argv(tmp_path / "absent-smoke.toml", tmp_path), environ=_demo_credentials())
    _refused(capsys, forbidden, code, names="absent-smoke.toml")


def test_an_invalid_smoke_limits_file_refuses_and_names_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    bad = tmp_path / "bad-smoke.toml"
    bad.write_text(
        TEST_ONLY_SMOKE_LIMITS.format(symbol="BTCUSDT").replace('"0.002"', "0.002"),
        encoding="utf-8",
    )
    code, _ = _execute(_argv(bad, tmp_path), environ=_demo_credentials())
    err = _refused(capsys, forbidden, code, names="bad-smoke.toml")
    assert "order.quantity" in err


def test_an_unconfigured_environment_refuses_before_the_prompt(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str], forbidden: list[str]
) -> None:
    code, reader = _execute(
        _argv(smoke_limits, tmp_path, environment="TESTNET"), environ=_demo_credentials()
    )
    err = _refused(capsys, forbidden, code, names="EnvironmentNotConfigured")
    assert reader.prompts == []
    assert "TESTNET" in err


def test_a_demo_websocket_url_not_configured_refuses(
    tmp_path: Path,
    smoke_limits: Path,
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
    code, _ = _execute(_argv(smoke_limits, tmp_path), environ=_demo_credentials())
    err = _refused(capsys, forbidden, code, names="WS_STREAMS")
    assert "EnvironmentNotConfigured" in err


def test_an_environment_violation_while_building_aborts_with_3(
    tmp_path: Path, smoke_limits: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def _violating_factory(config: uds.SmokeConfig) -> uds.SmokeRig:
        raise binance_client.EndpointViolation("DEMO REST endpoint does not match its row")

    code = uds.main(
        [*_argv(smoke_limits, tmp_path), "--execute"],
        environ=_demo_credentials(),
        is_tty=lambda: True,
        read_confirmation=lambda _p: PHRASE,
        rig_factory=_violating_factory,
        configure_output=lambda _env: None,
    )
    assert code == uds.EXIT_ABORTED
    assert "ABORTED before any order" in capsys.readouterr().err


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
                    text = ast.unparse(arg)
                    assert ".env" not in text, text


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
        if isinstance(node.func, ast.Subscript):
            raise AssertionError("no subscript call on the environment")
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) in {"os.environ", "env"}:
            raise AssertionError(f"environment subscript: {ast.unparse(node)}")


def test_the_script_never_constructs_the_sdk_rest_client_itself() -> None:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            assert ast.unparse(node.func) != "DerivativesTradingUsdsFutures"


def test_only_the_live_rig_reads_the_wall_clock() -> None:
    tree = _tree()
    owners: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def _visit(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit
        visit_AsyncFunctionDef = _visit

        def visit_Call(self, node: ast.Call) -> None:
            text = ast.unparse(node.func)
            if text in {"datetime.now", "datetime.utcnow", "time.time", "time.time_ns"}:
                owners.append(self.stack[-1] if self.stack else "<module>")
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert owners == ["_wall_clock"]


def test_only_the_live_rig_uses_the_real_sleep() -> None:
    tree = _tree()
    function = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_live_rig"
    )
    real_sleeps = {"asyncio.sleep", "time.sleep"}
    everywhere = [
        n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and ast.unparse(n) in real_sleeps
    ]
    inside = [
        n
        for n in ast.walk(function)
        if isinstance(n, ast.Attribute) and ast.unparse(n) in real_sleeps
    ]
    assert len(everywhere) == len(inside) == 1
