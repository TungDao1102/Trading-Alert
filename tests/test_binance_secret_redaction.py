"""Credential loading and secret redaction for the Binance client (plan 18-04, D-13, OPS-02).

Every test is offline and hermetic: credentials are random values generated per test,
variable names are TEST_ONLY names (the real names are owner-open until plan 18-09), key
files live under pytest's `tmp_path` (outside the repository), and `.env` is never read.
"""

from __future__ import annotations

import inspect
import io
import json
import logging
import secrets
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import structlog
from binance_common.errors import NetworkError
from src.adapters import binance_client as bc
from src.ops import redaction
from src.ops.redaction import RedactingFilter, configure_logging, scrub

REPO_ROOT = Path(__file__).resolve().parents[1]

# TEST_ONLY variable names. Deliberately free of any secret-looking fragment, so only the
# runtime registration (not the environment-name rule) can redact their values.
DEMO_SPEC = bc.CredentialSpec(key_variable="TEST_ONLY_DEMO_A", secret_variable="TEST_ONLY_DEMO_B")
LIVE_SPEC = bc.CredentialSpec(key_variable="TEST_ONLY_LIVE_A", secret_variable="TEST_ONLY_LIVE_B")


@pytest.fixture(autouse=True)
def _isolated_redactor() -> Iterator[None]:
    redaction.clear_runtime_secrets()
    redaction.uninstall_global_hooks()
    yield
    redaction.clear_runtime_secrets()
    redaction.uninstall_global_hooks()


def _value() -> str:
    return secrets.token_hex(32)


def _no_leak(secret: str, text: str) -> None:
    if secret in text:
        pytest.fail(f"a secret of length {len(secret)} leaked into {len(text)} chars of output")


class RecordingEnviron(Mapping[str, str]):
    """A read-only environ that records every name looked up (get, [] and `in`)."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.looked_up: list[str] = []

    def __getitem__(self, name: str) -> str:
        self.looked_up.append(name)
        return self._values[name]

    def __contains__(self, name: object) -> bool:
        self.looked_up.append(str(name))
        return name in self._values

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("the loader must not enumerate the environment")

    def __len__(self) -> int:
        return len(self._values)


def _load(environ: Mapping[str, str], **kwargs: Any) -> bc.ApiCredentials:
    return bc.load_api_credentials(environ, spec=DEMO_SPEC, repo_root=REPO_ROOT, **kwargs)


def _key_file(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Loading from the environment and from files.
# --------------------------------------------------------------------------- #


def test_credentials_load_from_environment_variables() -> None:
    key, secret = _value(), _value()
    creds = _load({"TEST_ONLY_DEMO_A": key, "TEST_ONLY_DEMO_B": f" {secret}\n"})
    assert (creds.api_key, creds.api_secret) == (key, secret)


def test_credentials_load_from_files_outside_the_repository(tmp_path: Path) -> None:
    key, secret = _value(), _value()
    key_path = _key_file(tmp_path, "a.txt", key + "\r\n")
    secret_path = _key_file(tmp_path, "b.txt", secret + " \n\n")
    creds = _load(
        {"TEST_ONLY_DEMO_A_FILE": str(key_path), "TEST_ONLY_DEMO_B_FILE": str(secret_path)}
    )
    assert (creds.api_key, creds.api_secret) == (key, secret)


def test_injected_file_reader_is_used(tmp_path: Path) -> None:
    key, secret = _value(), _value()
    key_path = _key_file(tmp_path, "a.txt", "ignored")
    secret_path = _key_file(tmp_path, "b.txt", "ignored")
    contents = {key_path.resolve(): key, secret_path.resolve(): secret + "\n"}
    creds = _load(
        {"TEST_ONLY_DEMO_A_FILE": str(key_path), "TEST_ONLY_DEMO_B_FILE": str(secret_path)},
        read_file=lambda path: contents[path],
    )
    assert (creds.api_key, creds.api_secret) == (key, secret)


def test_file_loading_refused_inside_the_repository() -> None:
    inside = REPO_ROOT / "pyproject.toml"
    assert inside.is_file()
    with pytest.raises(bc.CredentialError) as info:
        _load({"TEST_ONLY_DEMO_A_FILE": str(inside), "TEST_ONLY_DEMO_B": _value()})
    message = str(info.value)
    assert "TEST_ONLY_DEMO_A_FILE" in message
    assert "repository" in message
    assert str(inside) not in message
    assert "pyproject" not in message


def test_file_loading_refused_inside_the_repository_through_a_relative_hop() -> None:
    hop = REPO_ROOT / "src" / ".." / "pyproject.toml"
    with pytest.raises(bc.CredentialError) as info:
        _load({"TEST_ONLY_DEMO_A_FILE": str(hop), "TEST_ONLY_DEMO_B": _value()})
    message = str(info.value)
    # Refused for the property named here, not as "relative path" or "unreadable".
    assert "TEST_ONLY_DEMO_A_FILE" in message
    assert "repository" in message
    assert str(hop) not in message
    assert "pyproject" not in message


@pytest.mark.parametrize("case", ["relative", "missing", "directory", "empty", "blank-path"])
def test_bad_credential_files_are_refused_naming_the_variable_only(
    tmp_path: Path, case: str
) -> None:
    content = _value()
    if case == "relative":
        path_value = "some/relative/key.txt"
    elif case == "missing":
        path_value = str(tmp_path / "absent.txt")
    elif case == "directory":
        path_value = str(tmp_path)
    elif case == "empty":
        path_value = str(_key_file(tmp_path, "empty.txt", " \n\t\n"))
    else:
        path_value = "   "
    with pytest.raises(bc.CredentialError) as info:
        _load({"TEST_ONLY_DEMO_A_FILE": path_value, "TEST_ONLY_DEMO_B": content})
    message = str(info.value)
    assert "TEST_ONLY_DEMO_A_FILE" in message
    assert content not in message
    if path_value.strip():
        assert path_value not in message


def test_ambiguous_variable_plus_file_is_refused(tmp_path: Path) -> None:
    key = _value()
    path = _key_file(tmp_path, "a.txt", _value())
    with pytest.raises(bc.CredentialError) as info:
        _load(
            {
                "TEST_ONLY_DEMO_A": key,
                "TEST_ONLY_DEMO_A_FILE": str(path),
                "TEST_ONLY_DEMO_B": _value(),
            }
        )
    message = str(info.value)
    assert "ambiguous" in message
    assert "TEST_ONLY_DEMO_A" in message
    assert key not in message
    assert str(path) not in message


def test_live_variables_not_read_for_demo() -> None:
    environ = RecordingEnviron(
        {
            "TEST_ONLY_LIVE_A": _value(),
            "TEST_ONLY_LIVE_B": _value(),
            "TEST_ONLY_LIVE_A_FILE": "/nowhere",
        }
    )
    with pytest.raises(bc.CredentialError) as info:
        _load(environ)
    assert "TEST_ONLY_DEMO_A" in str(info.value)
    assert not any(name.startswith("TEST_ONLY_LIVE") for name in environ.looked_up)


def test_refuse_if_present_blocks_loading_when_another_spec_is_set() -> None:
    demo_key, demo_secret = _value(), _value()
    for live_name in ("TEST_ONLY_LIVE_A", "TEST_ONLY_LIVE_B", "TEST_ONLY_LIVE_B_FILE"):
        environ = {
            "TEST_ONLY_DEMO_A": demo_key,
            "TEST_ONLY_DEMO_B": demo_secret,
            live_name: _value(),
        }
        with pytest.raises(bc.CredentialError) as info:
            _load(environ, refuse_if_present=(LIVE_SPEC,))
        assert live_name in str(info.value)
        assert environ[live_name] not in str(info.value)
    # Refused means nothing was loaded: the DEMO values were never registered.
    assert demo_key in scrub(f"x {demo_key} y")
    # Without any LIVE variable the same call loads.
    creds = _load(
        {"TEST_ONLY_DEMO_A": demo_key, "TEST_ONLY_DEMO_B": demo_secret},
        refuse_if_present=(LIVE_SPEC,),
    )
    assert creds.api_key == demo_key


def test_no_key_parameter_signature() -> None:
    for function in (bc.load_api_credentials, bc.build_sdk_client):
        for name in inspect.signature(function).parameters:
            if name == "credentials":
                continue
            lowered = name.lower()
            assert "key" not in lowered, (function.__name__, name)
            assert "secret" not in lowered, (function.__name__, name)


# --------------------------------------------------------------------------- #
# Runtime registration: loaded values are scrubbed from every output path.
# --------------------------------------------------------------------------- #


def test_loaded_values_are_registered_with_the_redactor(tmp_path: Path) -> None:
    key, secret = _value(), _value()
    text = f"key={key} secret={secret}"
    assert scrub(text) == text  # control: nothing in the environment matches these names
    _load(
        {
            "TEST_ONLY_DEMO_A": key,
            "TEST_ONLY_DEMO_B_FILE": str(_key_file(tmp_path, "b.txt", secret)),
        }
    )
    cleaned = scrub(text)
    _no_leak(key, cleaned)
    _no_leak(secret, cleaned)
    assert cleaned == "key=[REDACTED] secret=[REDACTED]"


def test_registered_values_scrubbed_from_stdlib_and_structlog_output() -> None:
    key, secret = _value(), _value()
    listen_key = secrets.token_urlsafe(48).replace("-", "a").replace("_", "b")[:64]
    buffer = io.StringIO()
    configure_logging(environ={}, stream=buffer)
    _load({"TEST_ONLY_DEMO_A": key, "TEST_ONLY_DEMO_B": secret})
    redaction.register_runtime_secret(listen_key)

    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        # The SDK logs through the root logger with module-level calls (research P3).
        logging.info(f"Subscribing to streams on WebSocket 1: ['{listen_key}']")
        logging.info("headers %s", {"X-MBX-APIKEY": key, "secret": secret})
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)

    structlog.get_logger().info(
        "client_built", detail=f"key {key}", note=[secret], stream=f"/private/{listen_key}"
    )
    stdlib_output = capture.getvalue()
    structlog_output = buffer.getvalue()
    assert "Subscribing to streams on WebSocket 1" in stdlib_output
    assert "client_built" in structlog_output
    for output in (stdlib_output, structlog_output):
        for planted in (key, secret, listen_key):
            _no_leak(planted, output)
        assert "[REDACTED]" in output


def test_network_error_signature_and_registered_key_are_scrubbed() -> None:
    key, secret = _value(), _value()
    signature = secrets.token_hex(32)
    _load({"TEST_ONLY_DEMO_A": key, "TEST_ONLY_DEMO_B": secret})
    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("test.binance.network")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        try:
            raise NetworkError(
                error_message=(
                    "Network error: HTTPSConnectionPool(host='demo-fapi.binance.com', "
                    "port=443): Max retries exceeded with url: /fapi/v1/order?symbol=BTCUSDT"
                    f"&timestamp=1&signature={signature} (Caused by key {key})"
                )
            )
        except NetworkError:
            logger.error("order request failed", exc_info=True)
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
    output = capture.getvalue()
    assert "NetworkError" in output
    for planted in (key, secret, signature):
        _no_leak(planted, output)


# --------------------------------------------------------------------------- #
# listenKey rules (research P3).
# --------------------------------------------------------------------------- #


def test_listenkey_key_name_rule_masks_structlog_values() -> None:
    buffer = io.StringIO()
    configure_logging(environ={}, stream=buffer)
    structlog.get_logger().info(
        "stream", listenKey="short", listen_key="x", listenkey=123, symbol="BTCUSDT"
    )
    record = json.loads(buffer.getvalue().strip().splitlines()[-1])
    assert record["listenKey"] == "[REDACTED]"
    assert record["listen_key"] == "[REDACTED]"
    assert record["listenkey"] == "[REDACTED]"
    assert record["symbol"] == "BTCUSDT"


def test_listenkey_shape_rules_mask_query_and_json_forms() -> None:
    value = secrets.token_hex(32)
    text = (
        f"PUT /fapi/v1/listenKey?listenKey={value}&x=1\n"
        f'{{"listenKey": "{value}"}}\n'
        f"{{'listenKey': '{value}'}}\n"
        f"listen_key={value}"
    )
    cleaned = scrub(text)
    _no_leak(value, cleaned)
    assert cleaned.count("[REDACTED]") == 4
    assert "&x=1" in cleaned
    assert "/fapi/v1/listenKey?" in cleaned


def test_register_runtime_secret_is_idempotent_and_ignores_short_values() -> None:
    value = _value()
    redaction.register_runtime_secret(value)
    redaction.register_runtime_secret(value)
    assert scrub(f"a {value} b") == "a [REDACTED] b"
    short = "x" * (redaction.MIN_SECRET_LENGTH - 1)
    redaction.register_runtime_secret(short)
    assert scrub(f"a {short} b") == f"a {short} b"
    redaction.clear_runtime_secrets()
    assert scrub(f"a {value} b") == f"a {value} b"
