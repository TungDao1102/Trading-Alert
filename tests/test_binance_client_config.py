"""Environment selection, endpoint guard and the single SDK client factory (plan 18-04, D-12).

Every test is offline. The transport-level test patches `requests.Session.request`, so no
socket is ever opened, and every credential below is an obviously fake value. Nothing here
reads `.env`, a database URL or a real key.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import requests
from binance_common.constants import (
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
)
from src.adapters import binance_client as bc
from src.adapters.binance_usdm import BinanceUsdmAdapter
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
        {"T_KEY": FAKE_KEY, "T_SECRET": FAKE_SECRET}, spec=TEST_ONLY_SPEC
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


def test_environment_rows_come_from_the_sdk_constants() -> None:
    demo = bc.ENVIRONMENT_ROWS[bc.Environment.DEMO]
    assert demo.rest_url == DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
    # Owner-open (O-18-01 / plan 18-09): the DEMO WebSocket URLs are not configured here.
    assert demo.ws_streams_url is None
    assert demo.ws_api_url is None
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
        bc.load_api_credentials(env, spec=TEST_ONLY_SPEC)
    assert missing in str(info.value)
    blank = {"T_KEY": FAKE_KEY, "T_SECRET": FAKE_SECRET, missing: "   "}
    with pytest.raises(bc.CredentialError) as info:
        bc.load_api_credentials(blank, spec=TEST_ONLY_SPEC)
    assert missing in str(info.value)
    assert FAKE_KEY not in str(info.value)
    assert FAKE_SECRET not in str(info.value)


def test_credential_names_are_not_ratified_in_this_plan() -> None:
    assert dict(bc.CREDENTIAL_SPECS) == {}
    for environment in bc.Environment:
        with pytest.raises(bc.CredentialNamesNotRatified):
            bc.credential_spec_for(environment)


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


@pytest.mark.parametrize("surface", [bc.Surface.WS_STREAMS, bc.Surface.WS_API])
def test_demo_websocket_surface_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, surface: bc.Surface
) -> None:
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
