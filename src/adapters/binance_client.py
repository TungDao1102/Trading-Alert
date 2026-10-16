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
* Every URL comes from one ``EnvironmentRow``. Every row URL is an SDK constant except the
  DEMO WebSocket Streams URL, for which the SDK has no constant: it is the user's recorded
  value (plan 18-09), the only host literal in this module, and
  ``tests/test_binance_client_config.py`` pins it to the record. A surface (REST,
  WebSocket Streams, WebSocket API) that was not requested is configured with an inert
  ``.invalid`` URL so the SDK's lazy properties can never fall back to their mainnet
  defaults.
* ``assert_environment`` re-reads every surface of a built client and compares it with the
  row before use; ``assert_endpoint_url`` accepts only the exact row URL.
* LIVE additionally requires an enablement state whose ``is_disabled`` is ``False``. This
  module never enables LIVE.
* ``ClientLimits`` (F-504: explicit REST timeout, SDK retries and backoff) has no default
  values; the ratified numbers come from plan 18-09, never from this module.

The owner-open values (O-18-01 / O-18-04) are the user's decision, recorded in
``.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md`` on
2026-10-16 and copied here by plan 18-09: the DEMO WebSocket Streams URL is configured, the
DEMO WebSocket API URL and the whole ``TESTNET`` row stay NOT_CONFIGURED, and the credential
variable names exist for DEMO and LIVE only. ``tests/test_binance_limits_ratified_file.py``
compares the rows and the names with the record. Selecting an unconfigured surface raises
``EnvironmentNotConfigured``; asking for unratified credential names (TESTNET) raises
``CredentialNamesNotRatified``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
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
from src.ops.redaction import register_runtime_secret

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


# The rows are the user's decision (O-18-01 / O-18-04), copied by plan 18-09 from the record
# .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md (2026-10-16).
# Every configured URL is an SDK constant except the DEMO WebSocket Streams URL (no SDK
# constant exists for it). None means NOT_CONFIGURED: selecting that surface raises.
ENVIRONMENT_ROWS: Mapping[Environment, EnvironmentRow] = MappingProxyType(
    {
        Environment.DEMO: EnvironmentRow(
            environment=Environment.DEMO,
            rest_url=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
            # The user's value, record line 44 ("env DEMO ws_streams_url: ...").
            ws_streams_url="wss://demo-fstream.binance.com",
            # Record line 45: "env DEMO ws_api_url: NOT_CONFIGURED".
            ws_api_url=None,
        ),
        # Record line 46: "env TESTNET: NOT_CONFIGURED" (the whole row stays unconfigured).
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


# The SDK's WebSocket Streams class appends exactly this path to ``stream_url`` the first time
# the lazy ``websocket_streams`` property is read (``WebSocketStreamBase.__init__``), so the
# guard accepts the row URL with or without it and nothing else.
SDK_STREAMS_PATH_SUFFIX = "/stream"


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


# The user's credential variable NAMES (record 18-DEC-O-18-01.md lines 47 to 50, copied by
# plan 18-09). TESTNET has no ratified names, so credential_spec_for(TESTNET) still raises.
CREDENTIAL_SPECS: Mapping[Environment, CredentialSpec] = MappingProxyType(
    {
        Environment.DEMO: CredentialSpec(
            key_variable="BINANCE_DEMO_API_KEY",
            secret_variable="BINANCE_DEMO_API_SECRET",
        ),
        Environment.LIVE: CredentialSpec(
            key_variable="BINANCE_LIVE_API_KEY",
            secret_variable="BINANCE_LIVE_API_SECRET",
        ),
    }
)


def credential_spec_for(environment: Environment) -> CredentialSpec:
    """The ratified credential names of ``environment``; raises while they are owner-open."""
    spec = CREDENTIAL_SPECS.get(environment)
    if spec is None:
        raise CredentialNamesNotRatified(
            f"credential variable names for {environment.value} are not ratified (plan 18-09)"
        )
    return spec


FILE_SUFFIX = "_FILE"

FileReader = Callable[[Path], str]


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_from_file(
    file_variable: str, raw_path: str, repo_root: Path, read_file: FileReader
) -> str:
    """Read one credential from the file named by ``file_variable``. Errors name it only."""
    if not raw_path.strip():
        raise CredentialError(f"environment variable {file_variable} is blank")
    path = Path(raw_path)
    if not path.is_absolute():
        raise CredentialError(f"environment variable {file_variable} must name an absolute path")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise CredentialError(
            f"environment variable {file_variable} does not name an existing file"
        ) from None
    if not resolved.is_file():
        raise CredentialError(f"environment variable {file_variable} does not name a regular file")
    if resolved.is_relative_to(repo_root.resolve()):
        raise CredentialError(
            f"environment variable {file_variable} names a file inside the repository"
        )
    try:
        content = read_file(resolved)
    except (OSError, UnicodeDecodeError):
        raise CredentialError(
            f"environment variable {file_variable} names a file that cannot be read"
        ) from None
    value = content.strip()
    if not value:
        raise CredentialError(f"environment variable {file_variable} names an empty file")
    return value


def _load_one(environ: Mapping[str, str], name: str, repo_root: Path, read_file: FileReader) -> str:
    file_variable = name + FILE_SUFFIX
    direct = environ.get(name)
    raw_path = environ.get(file_variable)
    if direct is not None and raw_path is not None:
        raise CredentialError(
            f"ambiguous credential: both {name} and {file_variable} are set; set exactly one"
        )
    if raw_path is not None:
        return _read_from_file(file_variable, raw_path, repo_root, read_file)
    if direct is None or not direct.strip():
        raise CredentialError(
            f"environment variable {name} is missing or blank (set {name} or {file_variable})"
        )
    return direct.strip()


def load_api_credentials(
    environ: Mapping[str, str],
    *,
    spec: CredentialSpec,
    repo_root: Path,
    refuse_if_present: Sequence[CredentialSpec] = (),
    read_file: FileReader | None = None,
) -> ApiCredentials:
    """Load the key pair named by ``spec`` (D-13). Errors name a variable, never a value.

    Each value comes from ``<NAME>`` or from the file named by ``<NAME>_FILE`` (absolute,
    existing, regular, outside ``repo_root``, non-blank; surrounding whitespace stripped);
    both set is ambiguous and raises. Only the names of ``spec`` are read, so a LIVE key is
    never read for DEMO. If any variable of a ``refuse_if_present`` spec (or its ``_FILE``
    form) is present, nothing is loaded. There is no command-line path. On success the key
    and the secret are registered with the process redactor.
    """
    own = set(spec.variables)
    for other in refuse_if_present:
        for name in other.variables:
            if name in own:
                raise ValueError("refuse_if_present overlaps the loaded credential names")
            for candidate in (name, name + FILE_SUFFIX):
                if candidate in environ:
                    raise CredentialError(
                        f"environment variable {candidate} of another environment is set; "
                        "refusing to load credentials"
                    )
    reader = read_file if read_file is not None else _read_utf8
    root = Path(repo_root)
    api_key = _load_one(environ, spec.key_variable, root, reader)
    api_secret = _load_one(environ, spec.secret_variable, root, reader)
    register_runtime_secret(api_key)
    register_runtime_secret(api_secret)
    return ApiCredentials(api_key=api_key, api_secret=api_secret)


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
    inert URL (a streams URL may also carry the SDK's own ``/stream`` suffix, see
    ``SDK_STREAMS_PATH_SUFFIX``). The REST URL is read through ``client.rest_api`` (the
    object every request uses); the WebSocket URLs are read from the SDK's configuration
    attributes without triggering the lazy properties, plus the built surface object if one
    exists. Fails closed when the SDK object does not expose an expected attribute.
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
        accepted: tuple[str, ...] = (expected,)
        if surface is Surface.WS_STREAMS:
            accepted = (expected, expected + SDK_STREAMS_PATH_SUFFIX)
        for actual in actual_urls:
            if not _matches_any(actual, accepted):
                raise EndpointViolation(
                    f"{bundle.environment.value} {surface.value} endpoint does not match its "
                    "environment row"
                )


def _matches_any(actual: object, accepted: tuple[str, ...]) -> bool:
    for expected in accepted:
        try:
            assert_endpoint_url(actual, expected)
        except EndpointViolation:
            continue
        return True
    return False
