"""The exchange edge of the live process: one REST gate, one guarded adapter (plan 24-12).

`build_exchange` is the only construction site of the process-wide `RestRateLimitGate` under
`src/live` (DECISIONS D-15, 24-NOTES item 3). It builds, in this order:

  * the SDK client (`build_sdk_client`, or an injected factory for tests) for REST and the
    user-data stream surfaces of ONE explicit environment (DEMO or LIVE; TESTNET is refused);
  * a `FileGateStateStore` on the state volume and the gate on it, with the real alert hook and
    the optional D083 clock margin, so the gate reports `GATE_NOT_RESTORED` until the start
    sequence restores it (never `LEGACY_IN_MEMORY`, which no SAFE_MODE exit accepts);
  * a `ClockDriftGuard` from the ratified drift limits and the signed adapter built WITH it
    (D-06, 24-NOTES item 1): there is no parameter that builds the adapter without a guard, and a
    guard that was never measured makes `place_entry` raise `EntriesBlocked` before any SDK call;
  * the public market-data reader, the listen-key port and the probe adapter, all handed the SAME
    gate instance, so a 418 recorded through one holder refuses the next call of every other.

Nothing here restores or initializes the gate state (start-sequence step 2, plan 24-26), reads
the state file, sleeps, retries or opens a socket; the clock and sleep are injected and this
module reads no wall clock. The re-measure task body is `remeasure_drift`: it refreshes the
guard only when `needs_remeasure(now)` is true and never raises out of the scheduler. How often
the scheduler calls it is the ratified `drift.periodic_remeasure_interval_seconds` cadence, which
the guard itself applies through `needs_remeasure`.

The gate's alert hook takes a string (`REST_GATE_BAN_ENTERED until_utc=<ISO>` or
`REST_GATE_RECOVERY_REQUIRED`). `gate_alert_adapter` turns it into a structured `GateAlert`
(event name and, for a ban, the deadline) so the sink formatter route (plan 24-13) never sees a
message string and no exchange text can reach an alert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from binance_common.configuration import ConfigurationWebSocketStreams

from src.adapters import binance_client
from src.adapters.binance_client import (
    ApiCredentials,
    Environment,
    EnvironmentNotConfigured,
    LiveEnablementState,
    Surface,
)
from src.adapters.binance_clock import ClockDriftGuard, DriftVerdict
from src.adapters.binance_limits import BinanceLimits
from src.adapters.binance_probe import BinanceProbeAdapter
from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_ratelimit_gate import (
    REST_GATE_BAN_ENTERED,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.adapters.binance_userdata import SdkListenKeyPort
from src.execution.execution_limits import ExecutionLimits
from src.ops.rest_gate_state import FileGateStateStore

_log = structlog.get_logger(__name__)

# The surfaces the live process uses: signed REST and the user-data stream. No WS API.
LIVE_SURFACES: frozenset[Surface] = frozenset({Surface.REST, Surface.WS_STREAMS})

_UNTIL_PREFIX = "until_utc="

SdkFactory = Callable[..., Any]
SleepFn = Callable[[float], Awaitable[None]]


class ExchangeCompositionError(ValueError):
    """The exchange edge cannot be composed as configured (a named refusal, never a fallback)."""


class GateStatePathInvalid(ExchangeCompositionError):
    """The gate state path is not an absolute path with an existing parent directory.

    The gate never falls back to memory: a state file that cannot be placed is a refusal.
    """


@dataclass(frozen=True, kw_only=True)
class GateAlert:
    """One alert of the REST gate: the event name and, for a ban, the gate's own deadline.

    Carries no message text. `until_utc` is None for every event but `REST_GATE_BAN_ENTERED`
    (and for a ban string whose deadline does not parse).
    """

    event: str
    until_utc: datetime | None


def gate_alert_adapter(on_gate_alert: Callable[[GateAlert], None]) -> Callable[[str], None]:
    """The gate's `on_alert` hook over a structured sink call.

    Reads only the event token and, for a ban, the ISO deadline the gate itself wrote. The gate
    ignores an exception of the hook, so a failing sink never changes the restriction.
    """
    if not callable(on_gate_alert):
        raise TypeError("on_gate_alert must be callable")

    def hook(text: str) -> None:
        event, _, rest = text.partition(" ")
        until: datetime | None = None
        if event == REST_GATE_BAN_ENTERED and rest.startswith(_UNTIL_PREFIX):
            try:
                parsed = datetime.fromisoformat(rest[len(_UNTIL_PREFIX) :])
            except ValueError:
                parsed = None
            if parsed is not None and parsed.tzinfo is not None and parsed.utcoffset() is not None:
                until = parsed
        on_gate_alert(GateAlert(event=event, until_utc=until))

    return hook


@dataclass(frozen=True, kw_only=True)
class ExchangeBundle:
    """The exchange objects of the live process (every field required)."""

    mode: Environment
    sdk: Any
    gate_store: FileGateStateStore
    gate: RestRateLimitGate
    drift_guard: ClockDriftGuard
    adapter: BinanceUsdmAdapter
    public: BinancePublicMarketData
    listen_keys: SdkListenKeyPort
    probe: BinanceProbeAdapter
    stream_configuration: ConfigurationWebSocketStreams


def _validated_gate_state_path(path: object) -> Path:
    if not isinstance(path, Path):
        raise GateStatePathInvalid("gate_state_path must be a pathlib.Path")
    if not path.is_absolute():
        raise GateStatePathInvalid("gate_state_path must be absolute")
    if path.name == "" or path.is_dir():
        raise GateStatePathInvalid("gate_state_path must name a file")
    if not path.parent.is_dir():
        raise GateStatePathInvalid("the parent directory of gate_state_path must exist")
    return path


def build_exchange(
    *,
    mode: Environment,
    credentials: ApiCredentials,
    binance_limits: BinanceLimits,
    execution_limits: ExecutionLimits,
    clock: Callable[[], datetime],
    sleep: SleepFn,
    gate_state_path: Path,
    on_gate_alert: Callable[[GateAlert], None],
    sdk_factory: SdkFactory | None = None,
    live_enablement: LiveEnablementState | None = None,
) -> ExchangeBundle:
    """Compose the exchange edge (D-15, D-06); makes no network call and touches no state file.

    `sdk_factory` defaults to `build_sdk_client`; tests inject a fake. LIVE needs an enabled
    `live_enablement` (the existing `build_sdk_client` rule); DEMO does not. The gate is NOT
    restored here: the start sequence restores it (plan 24-26).
    """
    if not isinstance(mode, Environment):
        raise TypeError("mode must be an Environment")
    if mode is Environment.TESTNET:
        raise ExchangeCompositionError("the live process runs DEMO or LIVE, never TESTNET")
    if not isinstance(binance_limits, BinanceLimits):
        raise TypeError("binance_limits must be BinanceLimits")
    if not isinstance(execution_limits, ExecutionLimits):
        raise TypeError("execution_limits must be ExecutionLimits")
    if not callable(clock):
        raise TypeError("clock must be callable")
    state_path = _validated_gate_state_path(gate_state_path)
    row = binance_client.ENVIRONMENT_ROWS[mode]
    if row.ws_streams_url is None:
        raise EnvironmentNotConfigured(f"environment {mode.value} has no user-data stream URL")

    factory = sdk_factory if sdk_factory is not None else binance_client.build_sdk_client
    sdk = factory(
        environment=mode,
        credentials=credentials,
        limits=binance_limits.client,
        surfaces=LIVE_SURFACES,
        live_enablement=live_enablement,
    )
    if getattr(sdk, "environment", None) is not mode:
        raise ExchangeCompositionError("the SDK client was built for another environment")
    client = sdk.client

    store = FileGateStateStore(state_path, clock=clock)
    gate = RestRateLimitGate(
        policy=binance_limits.signed.rate_limit,
        clock=clock,
        state_store=store,
        on_alert=gate_alert_adapter(on_gate_alert),
        ban_end_clock_margin=execution_limits.rest_gate_ban_end_clock_margin,
    )
    drift_guard = ClockDriftGuard(limits=binance_limits.drift)
    adapter = BinanceUsdmAdapter(
        client,
        rest_gate=gate,
        sleep=sleep,
        signed_call_policy=binance_limits.signed,
        drift_guard=drift_guard,
        clock=clock,
        on_clock_skew=drift_guard.note_clock_skew_error,
    )
    public = BinancePublicMarketData(sdk_client=client, rest_gate=gate)
    listen_keys = SdkListenKeyPort(client.rest_api, rest_gate=gate)
    probe = BinanceProbeAdapter(client, policy=binance_limits.signed, rest_gate=gate, public=public)
    stream_configuration = ConfigurationWebSocketStreams(
        stream_url=row.ws_streams_url,
        reconnect_delay=binance_limits.stream.sdk_reconnect_delay_ms,
        reconnect_attempts=binance_limits.stream.sdk_reconnect_attempts,
    )
    return ExchangeBundle(
        mode=mode,
        sdk=sdk,
        gate_store=store,
        gate=gate,
        drift_guard=drift_guard,
        adapter=adapter,
        public=public,
        listen_keys=listen_keys,
        probe=probe,
        stream_configuration=stream_configuration,
    )


async def remeasure_drift(
    bundle: ExchangeBundle,
    *,
    clock_ms: Callable[[], int],
    now_utc: Callable[[], datetime],
) -> DriftVerdict | None:
    """The re-measure task body: refresh the guard only when it asks for a measurement.

    Returns the new verdict, or None when no measurement was due or the attempt itself failed.
    Never raises (cancellation excepted): a failed measure is a failed verdict, which the guard
    keeps blocking new entries on, and any other failure is logged by class name and leaves the
    guard asking for a re-measure (so the last verdict cannot count as fresh).
    """
    guard = bundle.drift_guard
    try:
        if not guard.needs_remeasure(now_utc()):
            return None
        return await guard.refresh(
            server_time=bundle.adapter.server_time, clock_ms=clock_ms, now_utc=now_utc
        )
    except Exception as exc:
        _log.warning("drift_remeasure_failed", error=type(exc).__name__)
        guard.request_remeasure()
        return None


__all__ = [
    "LIVE_SURFACES",
    "ExchangeBundle",
    "ExchangeCompositionError",
    "GateAlert",
    "GateStatePathInvalid",
    "build_exchange",
    "gate_alert_adapter",
    "remeasure_drift",
]
