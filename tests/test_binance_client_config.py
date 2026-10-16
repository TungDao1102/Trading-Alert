"""Environment selection, endpoint guard and the single SDK client factory (plan 18-04, D-12).

Every test is offline. The transport-level test patches `requests.Session.request`, so no
socket is ever opened, and every credential below is an obviously fake value. Nothing here
reads `.env`, a database URL or a real key.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import requests
from binance_common.configuration import (
    ConfigurationRestAPI,
    ConfigurationWebSocketAPI,
    ConfigurationWebSocketStreams,
)
from binance_common.constants import (
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_TESTNET_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL,
)
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from scripts import demo_rehearsal as dr
from src.adapters import binance_client as bc
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.execution.enablement import LiveEnablementController
from src.ops import redaction

# TEST_ONLY values: these are NOT ratified client limits (plan 18-09 ratifies them) and they
# are never imported from `src`. They exist only so a client can be built in a test.
TEST_ONLY_REST_TIMEOUT_MS = 1234
TEST_ONLY_SDK_RETRIES = 0
TEST_ONLY_SDK_BACKOFF_MS = 0

# Obviously fake credentials; their variable names are TEST_ONLY too.
FAKE_KEY = "FAKEKEY0123456789ABCDEF"
FAKE_SECRET = "FAKESECRET0123456789GHIJKL"
TEST_ONLY_SPEC = bc.CredentialSpec(key_variable="T_KEY", secret_variable="T_SECRET")


# The user's decision record (plan 18-09). The DEMO WebSocket expectations below are parsed from
# its `env DEMO <field>: <value>` lines at test time, never written as literals here.
DECISION_RECORD = (
    Path(__file__).resolve().parents[1]
    / ".planning"
    / "phases"
    / "18-user-data-stream-error-taxonomy"
    / "decisions"
    / "18-DEC-O-18-01.md"
)
NOT_CONFIGURED = "NOT_CONFIGURED"


def _record_env_field(environment: str, field_name: str) -> str | None:
    """The record's `env <ENV> <field>: <value>` value; None for NOT_CONFIGURED."""
    pattern = re.compile(rf"^env {environment} {field_name}: (\S+)\s*$", flags=re.MULTILINE)
    found = pattern.findall(DECISION_RECORD.read_text(encoding="utf-8"))
    assert len(found) == 1, f"the record must carry exactly one env {environment} {field_name}"
    return None if found[0] == NOT_CONFIGURED else str(found[0])


def _record_demo_streams_url() -> str:
    url = _record_env_field("DEMO", "ws_streams_url")
    assert url is not None, "the record configures the DEMO WebSocket Streams URL"
    return url


@pytest.fixture(autouse=True)
def _clean_runtime_secrets() -> Iterator[None]:
    yield
    clear = getattr(redaction, "clear_runtime_secrets", None)
    if clear is not None:
        clear()


def _limits() -> bc.ClientLimits:
    return bc.ClientLimits(
        rest_timeout_ms=TEST_ONLY_REST_TIMEOUT_MS,
        sdk_retries=TEST_ONLY_SDK_RETRIES,
        sdk_backoff_ms=TEST_ONLY_SDK_BACKOFF_MS,
    )


def _credentials() -> bc.ApiCredentials:
    return bc.load_api_credentials(
        {"T_KEY": FAKE_KEY, "T_SECRET": FAKE_SECRET}, spec=TEST_ONLY_SPEC, repo_root=REPO_ROOT
    )


def _demo_rest_bundle() -> bc.SdkClientBundle:
    return bc.build_sdk_client(
        environment=bc.Environment.DEMO,
        credentials=_credentials(),
        limits=_limits(),
        surfaces=frozenset({bc.Surface.REST}),
    )


# --------------------------------------------------------------------------- #
# Environment selection (no default, exact match).
# --------------------------------------------------------------------------- #


def test_parse_environment_accepts_the_exact_values() -> None:
    assert bc.parse_environment("DEMO") is bc.Environment.DEMO
    assert bc.parse_environment("TESTNET") is bc.Environment.TESTNET
    assert bc.parse_environment("LIVE") is bc.Environment.LIVE


@pytest.mark.parametrize("value", [None, "", " ", "\t"])
def test_parse_environment_without_a_value_raises(value: Any) -> None:
    with pytest.raises(bc.EnvironmentNotSelected):
        bc.parse_environment(value)


@pytest.mark.parametrize("value", ["demo", "demo ", " DEMO", "PROD", "mainnet", "Live", 1])
def test_parse_environment_unknown_value_raises(value: Any) -> None:
    with pytest.raises(bc.UnknownEnvironment):
        bc.parse_environment(value)


def test_environment_rows_come_from_the_sdk_constants_and_the_record() -> None:
    demo = bc.ENVIRONMENT_ROWS[bc.Environment.DEMO]
    assert demo.rest_url == DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
    # The DEMO WebSocket URLs are the user's record lines (plan 18-09); NOT_CONFIGURED is None.
    assert demo.ws_streams_url == _record_env_field("DEMO", "ws_streams_url")
    assert demo.ws_api_url == _record_env_field("DEMO", "ws_api_url")
    live = bc.ENVIRONMENT_ROWS[bc.Environment.LIVE]
    assert live.rest_url == DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    assert live.ws_streams_url == DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    assert live.ws_api_url == DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL
    testnet = bc.ENVIRONMENT_ROWS[bc.Environment.TESTNET]
    assert (testnet.rest_url, testnet.ws_streams_url, testnet.ws_api_url) == (None, None, None)
    assert set(bc.ENVIRONMENT_ROWS) == set(bc.Environment)
    with pytest.raises(TypeError):
        bc.ENVIRONMENT_ROWS[bc.Environment.TESTNET] = demo  # type: ignore[index]


def test_inert_url_uses_the_invalid_top_level_domain() -> None:
    assert bc.INERT_WS_URL == "wss://surface-not-requested.invalid"


# --------------------------------------------------------------------------- #
# ClientLimits (F-504): structure only, no defaults.
# --------------------------------------------------------------------------- #


def test_client_limits_has_no_defaults() -> None:
    with pytest.raises(TypeError):
        bc.ClientLimits()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        bc.ClientLimits(TEST_ONLY_REST_TIMEOUT_MS, 0, 0)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("timeout", "retries", "backoff"),
    [(0, 0, 0), (-1, 0, 0), (TEST_ONLY_REST_TIMEOUT_MS, -1, 0), (TEST_ONLY_REST_TIMEOUT_MS, 0, -1)],
)
def test_client_limits_rejects_out_of_range_values(
    timeout: int, retries: int, backoff: int
) -> None:
    with pytest.raises(ValueError):
        bc.ClientLimits(rest_timeout_ms=timeout, sdk_retries=retries, sdk_backoff_ms=backoff)


def test_client_limits_rejects_non_integers() -> None:
    with pytest.raises(ValueError):
        bc.ClientLimits(rest_timeout_ms=True, sdk_retries=0, sdk_backoff_ms=0)
    with pytest.raises(ValueError):
        bc.ClientLimits(rest_timeout_ms=1.5, sdk_retries=0, sdk_backoff_ms=0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Credentials from the environment.
# --------------------------------------------------------------------------- #


def test_load_api_credentials_from_environment_masks_repr() -> None:
    creds = _credentials()
    assert creds.api_key == FAKE_KEY
    assert creds.api_secret == FAKE_SECRET
    for rendered in (repr(creds), str(creds)):
        assert FAKE_KEY not in rendered
        assert FAKE_SECRET not in rendered


@pytest.mark.parametrize("missing", ["T_KEY", "T_SECRET"])
def test_load_api_credentials_missing_or_blank_names_the_variable_only(missing: str) -> None:
    env = {"T_KEY": FAKE_KEY, "T_SECRET": FAKE_SECRET}
    del env[missing]
    with pytest.raises(bc.CredentialError) as info:
        bc.load_api_credentials(env, spec=TEST_ONLY_SPEC, repo_root=REPO_ROOT)
    assert missing in str(info.value)
    blank = {"T_KEY": FAKE_KEY, "T_SECRET": FAKE_SECRET, missing: "   "}
    with pytest.raises(bc.CredentialError) as info:
        bc.load_api_credentials(blank, spec=TEST_ONLY_SPEC, repo_root=REPO_ROOT)
    assert missing in str(info.value)
    assert FAKE_KEY not in str(info.value)
    assert FAKE_SECRET not in str(info.value)


def test_credential_names_exist_only_for_the_environments_the_record_names() -> None:
    record = DECISION_RECORD.read_text(encoding="utf-8")
    named = set(re.findall(r"^credential ([A-Z]+) [a-z_]+: \S+\s*$", record, flags=re.MULTILINE))
    assert {environment.value for environment in bc.CREDENTIAL_SPECS} == named
    for environment in bc.Environment:
        if environment.value in named:
            assert bc.credential_spec_for(environment) is bc.CREDENTIAL_SPECS[environment]
        else:
            with pytest.raises(bc.CredentialNamesNotRatified):
                bc.credential_spec_for(environment)


def test_demo_and_live_credential_names_differ() -> None:
    """OPS-06: test-environment and live credential names never coincide."""
    demo = bc.credential_spec_for(bc.Environment.DEMO)
    live = bc.credential_spec_for(bc.Environment.LIVE)
    assert not set(demo.variables) & set(live.variables)


# --------------------------------------------------------------------------- #
# Factory and guard (tracer).
# --------------------------------------------------------------------------- #


def test_build_sdk_client_for_demo_rest_passes_the_guard() -> None:
    bundle = _demo_rest_bundle()
    assert bundle.environment is bc.Environment.DEMO
    assert bundle.surfaces == frozenset({bc.Surface.REST})
    bc.assert_environment(bundle)
    config = bundle.client.rest_api.configuration
    assert config.base_path == DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
    assert config.timeout == TEST_ONLY_REST_TIMEOUT_MS
    assert config.retries == TEST_ONLY_SDK_RETRIES
    assert config.backoff == TEST_ONLY_SDK_BACKOFF_MS
    # Unrequested surfaces carry the inert URL, never the SDK mainnet default.
    assert bundle.client._websocket_streams_config.stream_url == bc.INERT_WS_URL
    assert bundle.client._websocket_api_config.stream_url == bc.INERT_WS_URL
    assert bundle.client._websocket_api_config.api_key is None
    assert bundle.client._websocket_api_config.api_secret is None


class _Sentinel(Exception):  # noqa: N818 - a test marker, not an error taxonomy
    """Raised by the patched transport so no network error can masquerade as success."""


def _patch_transport(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake_request(self: requests.Session, *args: Any, **kwargs: Any) -> Any:
        seen.append(str(kwargs.get("url")))
        raise _Sentinel

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return seen


async def test_transport_level_demo_client_reaches_only_the_demo_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_transport(monkeypatch)
    bundle = _demo_rest_bundle()
    adapter = BinanceUsdmAdapter(sdk_client=bundle.client)
    with pytest.raises(_Sentinel):
        await adapter.server_time()
    with pytest.raises(_Sentinel):
        await adapter.exchange_info()
    assert len(seen) == 2
    assert all(url.startswith("https://demo-fapi.binance.com/") for url in seen)


def test_testnet_is_not_configured_and_raises_before_any_sdk_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_construction(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an SDK object was constructed")

    monkeypatch.setattr(bc, "DerivativesTradingUsdsFutures", no_construction)
    monkeypatch.setattr(bc, "ConfigurationRestAPI", no_construction)
    with pytest.raises(bc.EnvironmentNotConfigured) as info:
        bc.build_sdk_client(
            environment=bc.Environment.TESTNET,
            credentials=_credentials(),
            limits=_limits(),
            surfaces=frozenset({bc.Surface.REST}),
        )
    assert "TESTNET" in str(info.value)
    assert FAKE_KEY not in str(info.value)


_DEMO_WS_FIELDS = {bc.Surface.WS_STREAMS: "ws_streams_url", bc.Surface.WS_API: "ws_api_url"}


@pytest.mark.parametrize("surface", [bc.Surface.WS_STREAMS, bc.Surface.WS_API])
def test_demo_websocket_surface_follows_the_record(
    monkeypatch: pytest.MonkeyPatch, surface: bc.Surface
) -> None:
    """A NOT_CONFIGURED record answer keeps the surface raising before any SDK object."""
    recorded = _record_env_field("DEMO", _DEMO_WS_FIELDS[surface])
    if recorded is not None:
        seen = _patch_transport(monkeypatch)
        bundle = bc.build_sdk_client(
            environment=bc.Environment.DEMO,
            credentials=_credentials(),
            limits=_limits(),
            surfaces=frozenset({bc.Surface.REST, surface}),
        )
        bc.assert_environment(bundle)
        assert seen == []
        return

    def no_construction(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an SDK object was constructed")

    monkeypatch.setattr(bc, "DerivativesTradingUsdsFutures", no_construction)
    with pytest.raises(bc.EnvironmentNotConfigured) as info:
        bc.build_sdk_client(
            environment=bc.Environment.DEMO,
            credentials=_credentials(),
            limits=_limits(),
            surfaces=frozenset({bc.Surface.REST, surface}),
        )
    assert "DEMO" in str(info.value)
    assert surface.value in str(info.value)


def test_demo_all_surfaces_follow_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three DEMO surfaces build only when the record configures every one of them."""
    seen = _patch_transport(monkeypatch)
    configured = all(
        _record_env_field("DEMO", name) is not None for name in _DEMO_WS_FIELDS.values()
    )
    if configured:
        bundle = bc.build_sdk_client(
            environment=bc.Environment.DEMO,
            credentials=_credentials(),
            limits=_limits(),
            surfaces=_ALL_SURFACES,
        )
        bc.assert_environment(bundle)
    else:
        with pytest.raises(bc.EnvironmentNotConfigured):
            bc.build_sdk_client(
                environment=bc.Environment.DEMO,
                credentials=_credentials(),
                limits=_limits(),
                surfaces=_ALL_SURFACES,
            )
    assert seen == []


def _demo_streams_bundle() -> bc.SdkClientBundle:
    return bc.build_sdk_client(
        environment=bc.Environment.DEMO,
        credentials=_credentials(),
        limits=_limits(),
        surfaces=frozenset({bc.Surface.REST, bc.Surface.WS_STREAMS}),
    )


def test_demo_streams_client_carries_the_record_url_and_survives_the_sdk_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_transport(monkeypatch)
    expected = _record_demo_streams_url()
    bundle = _demo_streams_bundle()
    client = bundle.client
    assert client._websocket_streams_config.stream_url == expected
    assert client.rest_api.configuration.base_path == (
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
    )
    # The unrequested WebSocket API surface stays inert and unsigned.
    assert client._websocket_api_config.stream_url == bc.INERT_WS_URL
    assert client._websocket_api_config.api_key is None
    streams = client.websocket_streams  # constructs, never connects
    assert streams.configuration.stream_url == expected + bc.SDK_STREAMS_PATH_SUFFIX
    bc.assert_environment(bundle)
    assert seen == []


@pytest.mark.parametrize(
    "foreign",
    [
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL,
        bc.INERT_WS_URL,
        None,
    ],
)
def test_requested_demo_streams_surface_mutation_is_refused(foreign: Any) -> None:
    bundle = _demo_streams_bundle()
    bundle.client._websocket_streams_config.stream_url = foreign
    with pytest.raises(bc.EndpointViolation) as info:
        bc.assert_environment(bundle)
    assert "DEMO WS_STREAMS" in str(info.value)


def test_requested_demo_streams_near_misses_are_refused_by_the_guard() -> None:
    expected = _record_demo_streams_url()
    bundle = _demo_streams_bundle()
    for miss in _near_misses(expected):
        bundle.client._websocket_streams_config.stream_url = miss
        with pytest.raises(bc.EndpointViolation):
            bc.assert_environment(bundle)
    bundle.client._websocket_streams_config.stream_url = expected
    bc.assert_environment(bundle)


def test_build_sdk_client_requires_at_least_one_surface() -> None:
    with pytest.raises(ValueError):
        bc.build_sdk_client(
            environment=bc.Environment.DEMO,
            credentials=_credentials(),
            limits=_limits(),
            surfaces=frozenset(),
        )


def test_build_sdk_client_rejects_a_string_environment() -> None:
    with pytest.raises(bc.UnknownEnvironment):
        bc.build_sdk_client(
            environment="DEMO",  # type: ignore[arg-type]
            credentials=_credentials(),
            limits=_limits(),
            surfaces=frozenset({bc.Surface.REST}),
        )


# --------------------------------------------------------------------------- #
# Task 2: guard hardening for every surface and near-miss URL.
# --------------------------------------------------------------------------- #

_ALL_SDK_URLS = (
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_TESTNET_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL,
)

_GUARDED_URLS = {
    "demo-rest": DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
    "live-rest": DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    "live-streams": DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
    "live-ws-api": DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    # The user's DEMO WebSocket Streams URL, parsed from the record (plan 18-09).
    "demo-streams": _record_demo_streams_url(),
}


def _near_misses(expected: str) -> list[object]:
    parts = urlsplit(expected)
    host = parts.hostname or ""
    path = parts.path
    weak = {"https": "http", "wss": "ws"}[parts.scheme]
    other = {"https": "wss", "wss": "https"}[parts.scheme]
    misses: list[object] = [url for url in _ALL_SDK_URLS if url != expected]
    misses += [
        f"{weak}://{host}{path}",
        f"{other}://{host}{path}",
        f"{expected}/extra",
        f"{expected}/",
        f"{expected}?x=1",
        f"{expected}#frag",
        f"{parts.scheme}://{host}:8443{path}",
        f"{parts.scheme}://{host}@evil.example{path}",
        f"{parts.scheme}://user:pw@{host}{path}",
        f"{parts.scheme}://{host}.evil.example{path}",
        f"{parts.scheme}://{host.upper()}{path}",
        f"{parts.scheme}://evil-{host}{path}",
        f" {expected}",
        "",
        None,
        42,
        b"bytes",
    ]
    return misses


@pytest.mark.parametrize("label", sorted(_GUARDED_URLS))
def test_assert_endpoint_url_accepts_only_the_exact_row_url(label: str) -> None:
    expected = _GUARDED_URLS[label]
    bc.assert_endpoint_url(expected, expected)
    for miss in _near_misses(expected):
        with pytest.raises(bc.EndpointViolation):
            bc.assert_endpoint_url(miss, expected)


def test_assert_endpoint_url_errors_never_echo_the_url() -> None:
    expected = DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
    leaky = "https://user:pa55w0rdpa55w0rd@demo-fapi.binance.com"
    with pytest.raises(bc.EndpointViolation) as info:
        bc.assert_endpoint_url(leaky, expected)
    assert "pa55w0rd" not in str(info.value)


class _EnabledLive:
    """Test stub of the live enablement state with live orders ENABLED (never in src)."""

    @property
    def is_disabled(self) -> bool:
        return False


class _FakeJournal:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def record(self, event: Any) -> None:
        self.events.append(event)


def _live_bundle(surfaces: frozenset[bc.Surface]) -> bc.SdkClientBundle:
    return bc.build_sdk_client(
        environment=bc.Environment.LIVE,
        credentials=_credentials(),
        limits=_limits(),
        surfaces=surfaces,
        live_enablement=_EnabledLive(),
    )


_ALL_SURFACES = frozenset(bc.Surface)


def test_live_is_refused_with_the_default_disabled_controller() -> None:
    controller = LiveEnablementController(journal=_FakeJournal())
    assert controller.is_disabled is True
    for enablement in (None, controller):
        with pytest.raises(bc.LiveNotEnabled):
            bc.build_sdk_client(
                environment=bc.Environment.LIVE,
                credentials=_credentials(),
                limits=_limits(),
                surfaces=frozenset({bc.Surface.REST}),
                live_enablement=enablement,
            )


def test_live_builds_with_an_enabled_stub_and_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_transport(monkeypatch)
    bundle = _live_bundle(_ALL_SURFACES)
    bc.assert_environment(bundle)
    client = bundle.client
    assert client.rest_api.configuration.base_path == (
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    )
    assert client._websocket_streams_config.stream_url == (
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL
    )
    assert client._websocket_api_config.stream_url == (
        DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL
    )
    assert seen == []


def test_rest_base_path_mutation_is_refused() -> None:
    bundle = _demo_rest_bundle()
    bundle.client.rest_api.configuration.base_path = (
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    )
    with pytest.raises(bc.EndpointViolation) as info:
        bc.assert_environment(bundle)
    assert "DEMO REST" in str(info.value)


@pytest.mark.parametrize(
    "foreign",
    [
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL,
        None,
    ],
)
def test_unrequested_streams_surface_mutation_is_refused(foreign: Any) -> None:
    bundle = _demo_rest_bundle()
    bundle.client._websocket_streams_config.stream_url = foreign
    with pytest.raises(bc.EndpointViolation) as info:
        bc.assert_environment(bundle)
    assert "DEMO WS_STREAMS" in str(info.value)


@pytest.mark.parametrize(
    "foreign",
    [
        DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
        DERIVATIVES_TRADING_USDS_FUTURES_WS_API_TESTNET_URL,
        None,
    ],
)
def test_unrequested_ws_api_surface_mutation_is_refused(foreign: Any) -> None:
    bundle = _demo_rest_bundle()
    bundle.client._websocket_api_config.stream_url = foreign
    with pytest.raises(bc.EndpointViolation) as info:
        bc.assert_environment(bundle)
    assert "DEMO WS_API" in str(info.value)


def test_unrequested_rest_surface_is_inert_and_mutation_is_refused() -> None:
    bundle = _live_bundle(frozenset({bc.Surface.WS_STREAMS}))
    config = bundle.client.rest_api.configuration
    assert config.base_path == bc.INERT_REST_URL
    assert config.api_key is None
    assert config.api_secret is None
    bc.assert_environment(bundle)
    config.base_path = DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    with pytest.raises(bc.EndpointViolation):
        bc.assert_environment(bundle)


@pytest.mark.parametrize(
    ("attribute", "foreign"),
    [
        ("_websocket_streams_config", DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL),
        ("_websocket_api_config", DERIVATIVES_TRADING_USDS_FUTURES_WS_API_TESTNET_URL),
        ("_websocket_streams_config", bc.INERT_WS_URL),
        ("_websocket_api_config", bc.INERT_WS_URL),
    ],
)
def test_requested_websocket_surface_mutation_is_refused(attribute: str, foreign: str) -> None:
    bundle = _live_bundle(_ALL_SURFACES)
    getattr(bundle.client, attribute).stream_url = foreign
    with pytest.raises(bc.EndpointViolation):
        bc.assert_environment(bundle)


def test_unrequested_surfaces_accept_exactly_the_inert_url() -> None:
    bundle = _demo_rest_bundle()
    bundle.client._websocket_streams_config.stream_url = bc.INERT_WS_URL
    bundle.client._websocket_api_config.stream_url = bc.INERT_WS_URL
    bc.assert_environment(bundle)
    bundle.client._websocket_api_config.stream_url = bc.INERT_WS_URL + "/"
    with pytest.raises(bc.EndpointViolation):
        bc.assert_environment(bundle)


def test_guard_still_passes_after_the_sdk_lazy_streams_property_appends_its_suffix() -> None:
    """The SDK appends `/stream` to stream_url when `websocket_streams` is first read."""
    bundle = _live_bundle(_ALL_SURFACES)
    streams = bundle.client.websocket_streams  # constructs, never connects
    assert streams.configuration.stream_url == (
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL + "/stream"
    )
    bc.assert_environment(bundle)
    streams.configuration.stream_url = (
        DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_TESTNET_URL + "/stream"
    )
    with pytest.raises(bc.EndpointViolation):
        bc.assert_environment(bundle)
    streams.configuration.stream_url = DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL + "/x"
    with pytest.raises(bc.EndpointViolation):
        bc.assert_environment(bundle)


def test_guard_fails_closed_when_a_configuration_is_unreadable() -> None:
    bundle = _demo_rest_bundle()
    del bundle.client._websocket_api_config
    with pytest.raises(bc.EndpointViolation):
        bc.assert_environment(bundle)


# --------------------------------------------------------------------------- #
# Contract: the SDK internals the guard and the factory rely on.
# --------------------------------------------------------------------------- #


def test_sdk_internals_contract() -> None:
    client = DerivativesTradingUsdsFutures(
        config_rest_api=ConfigurationRestAPI(
            api_key=None,
            api_secret=None,
            base_path=bc.INERT_REST_URL,
            timeout=TEST_ONLY_REST_TIMEOUT_MS,
            retries=TEST_ONLY_SDK_RETRIES,
            backoff=TEST_ONLY_SDK_BACKOFF_MS,
        ),
        config_ws_api=ConfigurationWebSocketAPI(
            api_key=None, api_secret=None, stream_url=bc.INERT_WS_URL
        ),
        config_ws_streams=ConfigurationWebSocketStreams(stream_url=bc.INERT_WS_URL),
    )
    for name in ("_rest_api_config", "_websocket_api_config", "_websocket_streams_config"):
        assert hasattr(client, name)
    for name in ("_rest_api", "_websocket_api", "_websocket_streams"):
        assert getattr(client, name) is None
    assert client.rest_api.configuration is client._rest_api_config
    for cls, keywords in (
        (
            ConfigurationRestAPI,
            {"api_key", "api_secret", "base_path", "timeout", "retries", "backoff"},
        ),
        (ConfigurationWebSocketAPI, {"api_key", "api_secret", "stream_url"}),
        (ConfigurationWebSocketStreams, {"stream_url"}),
    ):
        assert keywords <= set(inspect.signature(cls.__init__).parameters)
    assert set(inspect.signature(DerivativesTradingUsdsFutures.__init__).parameters) >= {
        "config_rest_api",
        "config_ws_api",
        "config_ws_streams",
    }


# --------------------------------------------------------------------------- #
# Construction sites and source hygiene.
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every (file, enclosing scope) that calls `DerivativesTradingUsdsFutures(...)` in `src/`
# and `scripts/`, listed from a scan of the tree when plan 18-04 started.
ALLOWED_SDK_CONSTRUCTION_SITES = {
    # The single factory for a client that can sign requests (this plan).
    ("src/adapters/binance_client.py", "build_sdk_client"),
    # Phase 9 rehearsal builder: Demo REST only, kept unchanged by plan 18-04.
    ("scripts/demo_rehearsal.py", "build_demo_sdk_client"),
    # Pre-existing public-data default: REST configuration with no key and no secret.
    ("src/adapters/binance_public.py", "_credential_free_client"),
    # Pre-existing no-argument default of the order adapter (no credentials; callers that
    # sign inject a client built elsewhere).
    ("src/adapters/binance_usdm.py", "BinanceUsdmAdapter.__init__"),
}


class _ConstructionVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.sites: list[str] = []

    def _visit_scope(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = _visit_scope
    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name: str | None = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name == "DerivativesTradingUsdsFutures":
            self.sites.append(".".join(self.stack) if self.stack else "<module>")
        self.generic_visit(node)


def test_sdk_client_is_constructed_only_at_the_allowed_sites() -> None:
    found: set[tuple[str, str]] = set()
    for top in ("src", "scripts"):
        for path in sorted((REPO_ROOT / top).rglob("*.py")):
            visitor = _ConstructionVisitor()
            visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
            rel = path.relative_to(REPO_ROOT).as_posix()
            found |= {(rel, site) for site in visitor.sites}
    assert found == ALLOWED_SDK_CONSTRUCTION_SITES


def test_client_module_has_no_host_literal() -> None:
    """No LIVE host literal; the only host literal is the user's DEMO streams URL (18-09).

    The SDK has no constant for the DEMO WebSocket Streams host, so the row carries the
    record's URL as a literal. It is allowed exactly once, as the whole string constant, and
    only when it equals the record line; every other string constant and the rest of the
    source still carry no LIVE host.
    """
    source = (REPO_ROOT / "src/adapters/binance_client.py").read_text(encoding="utf-8")
    allowed = _record_demo_streams_url()
    hosts = {
        urlsplit(url).hostname
        for url in (
            DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
            DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
            DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
        )
    }
    allowed_constants = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == allowed:
                allowed_constants += 1
                continue
            for host in hosts:
                assert host is not None
                assert host not in node.value
    assert allowed_constants == 1
    assert not re.search(r"fapi\.binance\.com|fstream\.binance", source.replace(allowed, ""))


# --------------------------------------------------------------------------- #
# The Phase 9 rehearsal delegates to the production guard.
# --------------------------------------------------------------------------- #


def test_rehearsal_guard_delegates_to_assert_endpoint_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, str]] = []
    real = dr.assert_endpoint_url

    def spy(url: object, expected: str) -> None:
        calls.append((url, expected))
        real(url, expected)

    monkeypatch.setattr(dr, "assert_endpoint_url", spy)
    dr.assert_demo_base_url(DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL)
    assert calls == [
        (
            DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
            bc.ENVIRONMENT_ROWS[bc.Environment.DEMO].rest_url,
        )
    ]
    with pytest.raises(dr.DemoHostViolation) as info:
        dr.assert_demo_base_url(DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL)
    assert str(info.value) == f"base URL is not the Demo Trading host {dr.DEMO_HOST}"
    with pytest.raises(dr.DemoHostViolation) as info:
        dr.assert_demo_base_url(None)
    assert str(info.value) == "base URL is missing or not text"
