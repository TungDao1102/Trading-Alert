"""Explicit environment selection and the single Binance SDK client factory (Phase 18, D-12).

This module is the only place in ``src`` and ``scripts`` that may construct
``DerivativesTradingUsdsFutures`` for a client that can sign requests. The only other
construction sites are the pre-existing credential-free public-data defaults
(``src/adapters/binance_public.py`` and the no-argument default of
``src/adapters/binance_usdm.py``) and the Phase 9 rehearsal builder in
``scripts/demo_rehearsal.py``; ``tests/test_binance_client_config.py`` pins that list.

Rules this module enforces:

* There is no default environment. ``parse_environment`` accepts exactly ``DEMO``,
  ``TESTNET`` or ``LIVE``; a missing, blank or unknown value raises. Nothing is ever
  inferred from a host name.
* Every URL comes from one ``EnvironmentRow``, and every row URL is an SDK constant (no
  host literal lives in this module). A surface (REST, WebSocket Streams, WebSocket API)
  that was not requested is configured with an inert ``.invalid`` URL so the SDK's lazy
  properties can never fall back to their mainnet defaults.
* ``assert_environment`` re-reads every surface of a built client and compares it with the
  row before use; ``assert_endpoint_url`` accepts only the exact row URL.
* LIVE additionally requires an enablement state whose ``is_disabled`` is ``False``. This
  module never enables LIVE.
* ``ClientLimits`` (F-504: explicit REST timeout, SDK retries and backoff) has no default
  values; the ratified numbers come from plan 18-09, never from this module.

Owner-open values stay unconfigured here: the DEMO WebSocket URLs, the meaning of
``TESTNET`` and the credential variable names (O-18-01 / O-18-04, recorded by plan 18-09
in ``decisions/18-DEC-O-18-01.md``). Selecting an unconfigured surface raises
``EnvironmentNotConfigured``; asking for unratified credential names raises
``CredentialNamesNotRatified``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlsplit

from binance_common.configuration import (
    ConfigurationRestAPI,
    ConfigurationWebSocketAPI,
    ConfigurationWebSocketStreams,
)
from binance_common.constants import (
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
    DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
)
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures

# --------------------------------------------------------------------------- #
# Errors. Messages name the environment, the surface or a variable NAME only; never a
# URL (it could carry userinfo), a key, a secret or a file path.
# --------------------------------------------------------------------------- #


class EnvironmentNotSelected(Exception):  # noqa: N818 - public name fixed by plan 18-04
    """No environment value was given (None or blank)."""


class UnknownEnvironment(Exception):  # noqa: N818 - public name fixed by plan 18-04
    """The environment value is not exactly DEMO, TESTNET or LIVE."""


class EnvironmentNotConfigured(Exception):  # noqa: N818 - public name fixed by plan 18-04
    """The selected environment has no configured URL for a requested surface."""


class EndpointViolation(Exception):  # noqa: N818 - public name fixed by plan 18-04
    """A client URL is not exactly the URL of its environment row."""


class LiveNotEnabled(Exception):  # noqa: N818 - public name fixed by plan 18-04
    """LIVE was selected while the live enablement state is absent or disabled."""


class CredentialError(Exception):
    """A credential variable or file is missing, blank, ambiguous or refused (names only)."""


class CredentialNamesNotRatified(Exception):  # noqa: N818 - public name fixed by plan 18-04
    """The credential variable names of an environment are owner-open (plan 18-09)."""


# --------------------------------------------------------------------------- #
# Environment and surfaces.
# --------------------------------------------------------------------------- #


class Environment(StrEnum):
    """The three selectable Binance USD-M environments. There is no default."""

    DEMO = "DEMO"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class Surface(StrEnum):
    """The three transport surfaces of the SDK client."""

    REST = "REST"
    WS_STREAMS = "WS_STREAMS"
    WS_API = "WS_API"


def parse_environment(value: object) -> Environment:
    """Exact, case-sensitive match on the enum value; no default, no inference."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise EnvironmentNotSelected("no environment selected; expected DEMO, TESTNET or LIVE")
    if not isinstance(value, str):
        raise UnknownEnvironment("environment value is not text; expected DEMO, TESTNET or LIVE")
    for environment in Environment:
        if value == environment.value:
            return environment
    raise UnknownEnvironment("unknown environment value; expected DEMO, TESTNET or LIVE")


@dataclass(frozen=True)
class EnvironmentRow:
    """The URLs of one environment. ``None`` means not configured (selecting it raises)."""

    environment: Environment
    rest_url: str | None
    ws_streams_url: str | None
    ws_api_url: str | None

    def url_for(self, surface: Surface) -> str | None:
        if surface is Surface.REST:
            return self.rest_url
        if surface is Surface.WS_STREAMS:
            return self.ws_streams_url
        return self.ws_api_url


# Owner-open (O-18-01 / O-18-04): the DEMO WebSocket Streams and WebSocket API URLs and the
# whole TESTNET row (what TESTNET denotes) are NOT configured here. Plan 18-09 fills them from
# the owner's record in decisions/18-DEC-O-18-01.md. Every configured URL is an SDK constant.
ENVIRONMENT_ROWS: Mapping[Environment, EnvironmentRow] = MappingProxyType(
    {
        Environment.DEMO: EnvironmentRow(
            environment=Environment.DEMO,
            rest_url=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
            ws_streams_url=None,
            ws_api_url=None,
        ),
        Environment.TESTNET: EnvironmentRow(
            environment=Environment.TESTNET,
            rest_url=None,
            ws_streams_url=None,
            ws_api_url=None,
        ),
        Environment.LIVE: EnvironmentRow(
            environment=Environment.LIVE,
            rest_url=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
            ws_streams_url=DERIVATIVES_TRADING_USDS_FUTURES_WS_STREAMS_PROD_URL,
            ws_api_url=DERIVATIVES_TRADING_USDS_FUTURES_WS_API_PROD_URL,
        ),
    }
)

# The `.invalid` top-level domain never resolves (RFC 2606). An unrequested surface carries
# one of these so the SDK's lazy property can never substitute its mainnet default.
INERT_WS_URL = "wss://surface-not-requested.invalid"
INERT_REST_URL = "https://surface-not-requested.invalid"


def _inert_url(surface: Surface) -> str:
    return INERT_REST_URL if surface is Surface.REST else INERT_WS_URL


# --------------------------------------------------------------------------- #
# Client limits (F-504): structure only, every field required, no default value.
# --------------------------------------------------------------------------- #


def _require_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise ValueError(f"ClientLimits.{name} must be an int")
    return value


@dataclass(frozen=True, kw_only=True)
class ClientLimits:
    """Explicit REST timeout, SDK retry count and SDK backoff (F-504). No defaults.

    ``rest_timeout_ms`` is passed to ``ConfigurationRestAPI(timeout=...)`` (milliseconds,
    connect and read together); ``sdk_retries`` and ``sdk_backoff_ms`` to ``retries`` and
    ``backoff``. The ratified values come from plan 18-09.
    """

    rest_timeout_ms: int
    sdk_retries: int
    sdk_backoff_ms: int

    def __post_init__(self) -> None:
        if _require_int("rest_timeout_ms", self.rest_timeout_ms) <= 0:
            raise ValueError("ClientLimits.rest_timeout_ms must be positive")
        if _require_int("sdk_retries", self.sdk_retries) < 0:
            raise ValueError("ClientLimits.sdk_retries must not be negative")
        if _require_int("sdk_backoff_ms", self.sdk_backoff_ms) < 0:
            raise ValueError("ClientLimits.sdk_backoff_ms must not be negative")


# --------------------------------------------------------------------------- #
# Credentials.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CredentialSpec:
    """The environment variable NAMES of one key pair (never the values)."""

    key_variable: str
    secret_variable: str

    def __post_init__(self) -> None:
        for name in (self.key_variable, self.secret_variable):
            if not isinstance(name, str) or not name or name != name.strip():
                raise ValueError("credential variable names must be non-blank text")
        if self.key_variable == self.secret_variable:
            raise ValueError("key and secret variable names must differ")

    @property
    def variables(self) -> tuple[str, str]:
        return (self.key_variable, self.secret_variable)


@dataclass(frozen=True, repr=False)
class ApiCredentials:
    """A loaded key pair. Neither value ever appears in repr or str."""

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)

    def __repr__(self) -> str:
        return "ApiCredentials(<masked>)"

    __str__ = __repr__


# Owner-open until plan 18-09 records the names: no environment has ratified names yet.
CREDENTIAL_SPECS: Mapping[Environment, CredentialSpec] = MappingProxyType({})


def credential_spec_for(environment: Environment) -> CredentialSpec:
    """The ratified credential names of ``environment``; raises while they are owner-open."""
    spec = CREDENTIAL_SPECS.get(environment)
    if spec is None:
        raise CredentialNamesNotRatified(
            f"credential variable names for {environment.value} are not ratified (plan 18-09)"
        )
    return spec


def _read_variable(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise CredentialError(f"environment variable {name} is missing or blank")
    return value.strip()


def load_api_credentials(environ: Mapping[str, str], *, spec: CredentialSpec) -> ApiCredentials:
    """Read the key pair named by ``spec`` from ``environ``. Errors name the variable only."""
    return ApiCredentials(
        api_key=_read_variable(environ, spec.key_variable),
        api_secret=_read_variable(environ, spec.secret_variable),
    )


# --------------------------------------------------------------------------- #
# Factory and guard.
# --------------------------------------------------------------------------- #


class LiveEnablementState(Protocol):
    """The read-only view of the live enablement flag (``LiveEnablementController``)."""

    @property
    def is_disabled(self) -> bool: ...


@dataclass(frozen=True)
class SdkClientBundle:
    """A built SDK client together with the environment and surfaces it was built for."""

    environment: Environment
    surfaces: frozenset[Surface]
    client: DerivativesTradingUsdsFutures


def _require_live_enabled(live_enablement: LiveEnablementState | None) -> None:
    if live_enablement is None or live_enablement.is_disabled is not False:
        raise LiveNotEnabled("LIVE requires the live enablement state to be enabled")


def _configured_urls(environment: Environment, surfaces: frozenset[Surface]) -> dict[Surface, str]:
    row = ENVIRONMENT_ROWS[environment]
    urls: dict[Surface, str] = {}
    for surface in Surface:
        if surface not in surfaces:
            urls[surface] = _inert_url(surface)
            continue
        url = row.url_for(surface)
        if url is None:
            raise EnvironmentNotConfigured(
                f"environment {environment.value} has no configured URL for surface {surface.value}"
            )
        urls[surface] = url
    return urls


def build_sdk_client(
    *,
    environment: Environment,
    credentials: ApiCredentials,
    limits: ClientLimits,
    surfaces: frozenset[Surface],
    live_enablement: LiveEnablementState | None = None,
) -> SdkClientBundle:
    """Build the SDK client for one explicit environment and check every surface.

    The only place in this module that constructs ``DerivativesTradingUsdsFutures``. All
    three SDK configurations are built from one environment row; a surface that was not
    requested gets an inert ``.invalid`` URL and no credential.
    """
    if not isinstance(environment, Environment):
        raise UnknownEnvironment("environment must be an Environment value")
    if not isinstance(credentials, ApiCredentials):
        raise TypeError("credentials must be ApiCredentials")
    if not isinstance(limits, ClientLimits):
        raise TypeError("limits must be ClientLimits")
    requested = frozenset(surfaces)
    if not requested:
        raise ValueError("at least one surface must be requested")
    if not all(isinstance(surface, Surface) for surface in requested):
        raise ValueError("surfaces must be Surface values")
    if environment is Environment.LIVE:
        _require_live_enabled(live_enablement)
    urls = _configured_urls(environment, requested)

    rest_signed = Surface.REST in requested
    config_rest = ConfigurationRestAPI(
        api_key=credentials.api_key if rest_signed else None,
        api_secret=credentials.api_secret if rest_signed else None,
        base_path=urls[Surface.REST],
        timeout=limits.rest_timeout_ms,
        retries=limits.sdk_retries,
        backoff=limits.sdk_backoff_ms,
    )
    config_streams = ConfigurationWebSocketStreams(stream_url=urls[Surface.WS_STREAMS])
    ws_api_signed = Surface.WS_API in requested
    config_ws_api = ConfigurationWebSocketAPI(
        api_key=credentials.api_key if ws_api_signed else None,
        api_secret=credentials.api_secret if ws_api_signed else None,
        stream_url=urls[Surface.WS_API],
    )
    client = DerivativesTradingUsdsFutures(
        config_rest_api=config_rest,
        config_ws_api=config_ws_api,
        config_ws_streams=config_streams,
    )
    bundle = SdkClientBundle(environment=environment, surfaces=requested, client=client)
    assert_environment(bundle)
    return bundle


def assert_endpoint_url(url: object, expected: str) -> None:
    """Accept only ``url == expected`` with a clean shape; everything else raises.

    The scheme (https or wss) and the path come from ``expected``: a REST row URL has no
    path, while the SDK WebSocket API constant carries one. A port, userinfo, query,
    fragment, other path, a hostname suffix or an upper-case host is rejected. The error
    names no URL.
    """
    _check_expected(expected)
    expected_parts = urlsplit(expected)
    if not isinstance(url, str) or not url:
        raise EndpointViolation("endpoint URL is missing or not text")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise EndpointViolation("endpoint URL is not parseable") from None
    if (
        url != expected
        or parts.scheme != expected_parts.scheme
        or parts.netloc != expected_parts.hostname
        or parts.hostname != expected_parts.hostname
        or port is not None
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path != expected_parts.path
    ):
        raise EndpointViolation("endpoint URL does not match the configured environment")


def _check_expected(expected: str) -> None:
    """The row URL itself must be a clean https or wss URL (defence against a bad row)."""
    try:
        parts = urlsplit(expected)
        port = parts.port
    except (TypeError, ValueError, AttributeError):
        raise EndpointViolation("expected endpoint is not parseable") from None
    if (
        parts.scheme not in ("https", "wss")
        or not parts.hostname
        or parts.netloc != parts.hostname
        or port is not None
        or parts.query
        or parts.fragment
    ):
        raise EndpointViolation("expected endpoint is not a clean https or wss URL")


def _surface_url(client: Any, surface: Surface) -> list[object]:
    """Every live URL of ``surface`` without triggering a lazy WebSocket property."""
    if surface is Surface.REST:
        return [client.rest_api.configuration.base_path]
    config_name, built_name = (
        ("_websocket_streams_config", "_websocket_streams")
        if surface is Surface.WS_STREAMS
        else ("_websocket_api_config", "_websocket_api")
    )
    config: Any = getattr(client, config_name)
    urls: list[object] = [config.stream_url]
    built: Any = getattr(client, built_name)
    if built is not None:
        urls.append(built.configuration.stream_url)
    return urls


def assert_environment(bundle: SdkClientBundle) -> None:
    """Re-read every surface of ``bundle.client`` and check it against the environment row.

    A requested surface must carry exactly the row URL; an unrequested surface exactly the
    inert URL. Fails closed when the SDK object does not expose an expected attribute.
    """
    if not isinstance(bundle.environment, Environment):
        raise EndpointViolation("bundle environment is not an Environment value")
    row = ENVIRONMENT_ROWS[bundle.environment]
    for surface in Surface:
        if surface in bundle.surfaces:
            expected = row.url_for(surface)
            if expected is None:
                raise EnvironmentNotConfigured(
                    f"environment {bundle.environment.value} has no configured URL for "
                    f"surface {surface.value}"
                )
        else:
            expected = _inert_url(surface)
        try:
            actual_urls = _surface_url(bundle.client, surface)
        except AttributeError:
            raise EndpointViolation(
                f"{bundle.environment.value} {surface.value} configuration is not readable"
            ) from None
        for actual in actual_urls:
            try:
                assert_endpoint_url(actual, expected)
            except EndpointViolation:
                raise EndpointViolation(
                    f"{bundle.environment.value} {surface.value} endpoint does not match its "
                    "environment row"
                ) from None
