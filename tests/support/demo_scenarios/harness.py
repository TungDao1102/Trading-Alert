"""The scenario harness: labels, recorder, env options, the fake env factory (plan 25-08).

TEST_ONLY. One scenario is `async def run(env, recorder) -> str` (D-04, D-05). The CI twin builds
`env` with `build_fake_scenario_env` (the composed process on the Binance-semantics fake, every
step SYNTHETIC); the owner's Demo test builds it through the Demo fixture contract below. Phase
24's `SmokeEnv`, `EvidenceRecorder` and `run_composed_smoke` are reused by import, never copied.

Labels (one per recorded step, key `label`):

* SYNTHETIC            the fake: nothing here is observed on Demo
* DEMO_OBSERVED        a real Demo reaction to a real Demo state
* DEMO_FAULT_INJECTED  the TRIGGER was injected at a test seam (D-08); the reaction is the real
                       code's. An injected trigger is never DEMO_OBSERVED (`label_for`).
* NOT_OBSERVED         the scenario could not produce the event on Demo (for example a partial fill)

Demo fixture contract (implemented by plan 25-09 in `tests/demo/conftest.py` and `demo_env.py`,
used by every `tests/demo/test_demo_s<NN>_<slug>.py`; scenario plans never redefine them):

* fixture `scenario_recorder`: a callable `(scenario_id: str) -> ScenarioRecorder` in EXECUTE
  mode that writes into the phase evidence directory;
* fixture `make_demo_env`: an async callable `(recorder: ScenarioRecorder, options: EnvOptions)
  -> ScenarioEnv` that builds the composed process on Binance Demo with the options' fault
  objects installed at the production seams (`exchange_edge`, `sdk_factory`, the stores).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from scripts import demo_rehearsal as dr

from tests.support.demo_scenarios.catalog import by_id
from tests.support.fault_edge import FaultEdge, SdkFaults, StoreFaults
from tests.support.live_smoke_env import FakeSmokeEnv, build_fake_smoke_env

SYNTHETIC = dr.EVIDENCE_KIND_SYNTHETIC
DEMO_OBSERVED = dr.EVIDENCE_KIND_DEMO
DEMO_FAULT_INJECTED = "DEMO_FAULT_INJECTED"
NOT_OBSERVED = "NOT_OBSERVED"
LABELS: tuple[str, ...] = (SYNTHETIC, DEMO_OBSERVED, DEMO_FAULT_INJECTED, NOT_OBSERVED)

SCENARIO_EVIDENCE_SCHEMA = "demo-scenario-evidence/schema-1"
FIXTURE_SCENARIO_RECORDER = "scenario_recorder"
FIXTURE_MAKE_DEMO_ENV = "make_demo_env"


def label_for(env: Any, *, injected: bool) -> str:
    """The label of a step the scenario observed (or provoked) in `env`.

    A synthetic env is SYNTHETIC whatever `injected` says; a Demo env is DEMO_FAULT_INJECTED when
    the trigger was injected and DEMO_OBSERVED only when it was not.
    """
    if env.synthetic:
        return SYNTHETIC
    return DEMO_FAULT_INJECTED if injected else DEMO_OBSERVED


class ScenarioRecorder(dr.EvidenceRecorder):
    """`EvidenceRecorder` with the scenario schema, the file stem and one label per step.

    `default_label` is the label `add_step` gives (the smoke's own `_smoke_record` calls it); a
    scenario sets it from `env.label`. A recorder whose default is SYNTHETIC refuses any other
    label (T-25-19): a synthetic run can never hold a Demo-looking step.
    """

    def __init__(
        self,
        scenario_id: str,
        *,
        mode: dr.RunMode,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], datetime],
        default_label: str | None = None,
    ) -> None:
        super().__init__(
            mode=mode,
            scenario=scenario_id,
            symbol=dr.SYMBOL,
            base_url=dr.DEMO_BASE_URL,
            environ=environ or {},
            clock=clock,
        )
        by_id(scenario_id)  # an id outside the catalog is a typo, not a new scenario
        self.scenario_id = scenario_id
        if default_label is None:
            default_label = SYNTHETIC if mode is dr.RunMode.DRY_RUN else DEMO_OBSERVED
        self.default_label = _checked(default_label)

    def add_step(self, name: str, status: str, detail: str) -> None:
        self.add_labeled_step(name, status, detail, label=self.default_label)

    def add_labeled_step(self, name: str, status: str, detail: str, *, label: str) -> None:
        label = _checked(label)
        if self.default_label == SYNTHETIC and label != SYNTHETIC:
            raise ValueError(f"a synthetic run cannot record a {label} step")
        self.steps.append({"name": name, "status": status, "detail": detail, "label": label})

    def record_health(self, verdict: Any) -> None:
        """Facts of a health verdict only; whether it is healthy is the owner's answer (25-19)."""
        entry: dict[str, Any]
        if verdict is None:
            entry = {"is_no_trade": None, "degraded": [], "failing": [], "at": None}
        else:
            results = verdict.results
            entry = {
                "is_no_trade": verdict.is_no_trade,
                "degraded": list(verdict.degraded_names),
                "failing": [r.check_name for r in results if r.status == "FAIL"],
                "at": max((r.observed_at_utc for r in results), default=None),
            }
        self.details.setdefault("health", []).append(dr._jsonable(entry))

    def to_dict(self) -> dict[str, Any]:
        document = super().to_dict()
        document["schema"] = SCENARIO_EVIDENCE_SCHEMA
        document["scenario_id"] = self.scenario_id
        document["evidence_kinds"] = sorted({step["label"] for step in self.steps})
        return document

    def _file_stem(self) -> str:
        kind = "DRYRUN" if self.mode is dr.RunMode.DRY_RUN else "EVIDENCE"
        return f"25-DEMO-SCENARIO-{kind}-{self.scenario_id}-{dr._utc_stamp(self._started)}"


def _checked(label: str) -> str:
    if label not in LABELS:
        raise ValueError(f"unknown evidence label {label!r}; expected one of {LABELS}")
    return label


@dataclass(frozen=True)
class EnvOptions:
    """What a scenario asks of its env. `None` fault objects are created fresh by the factory.

    `clock_offset` shifts the process clock; only the Demo env supports it (the twin uses the
    existing drift-test technique), so the fake factory refuses a non-zero value.
    """

    faults: FaultEdge | None = None
    sdk_faults: SdkFaults | None = None
    store_faults: StoreFaults | None = None
    clock_offset: timedelta = timedelta(0)


class ScenarioEnv(Protocol):
    """The attributes a scenario may use: SmokeEnv's, the fault objects, `abandon`, `synthetic`."""

    assembly: Any
    clock: Callable[[], datetime]
    tick: Callable[[], Awaitable[None]]
    pause: Callable[[float], Awaitable[None]]
    owner: dr.SmokeOwner
    synthetic: bool
    wait_ticks: int
    ports_transform: Callable[[Any], Any]
    deliver_fill: Callable[[Any], Awaitable[None]] | None
    placements: Callable[[], int] | None
    restart: Callable[[], Awaitable[Any]] | None
    initialize_gate_state: bool
    faults: Any
    sdk_faults: Any
    store_faults: Any

    @property
    def wiring(self) -> Any: ...

    @property
    def label(self) -> str: ...

    async def abandon(self) -> None:
        """Release what a scenario that stops early left behind (a no-op on the fake)."""
        ...


@dataclass
class FakeScenarioEnv(FakeSmokeEnv):
    """The fake smoke env as a `ScenarioEnv`: the same fields plus a no-op `abandon`."""

    async def abandon(self) -> None:
        return None


def _adopt(env: FakeSmokeEnv) -> FakeScenarioEnv:
    """The fake smoke env as a scenario env; the env a restart builds is adopted the same way."""
    values = {field.name: getattr(env, field.name) for field in dataclasses.fields(env)}
    inner = values["restart"]
    if inner is not None:

        async def restart() -> FakeScenarioEnv:
            return _adopt(await inner())

        values["restart"] = restart
    return FakeScenarioEnv(**values)


def build_fake_scenario_env(tmp_path: Path, options: EnvOptions) -> FakeScenarioEnv:
    """The composed process on the Binance-semantics fake, with the options' fault objects.

    Memory stores only (D-02). Omitted fault objects are fresh, so `env.faults` and the other two
    are always usable by the scenario.
    """
    if options.clock_offset != timedelta(0):
        raise ValueError("clock_offset is a Demo env option; the twin cannot apply it")
    faults = options.faults if options.faults is not None else FaultEdge()
    sdk_faults = options.sdk_faults if options.sdk_faults is not None else SdkFaults()
    store_faults = options.store_faults if options.store_faults is not None else StoreFaults()
    smoke = build_fake_smoke_env(
        tmp_path, faults=faults, sdk_faults=sdk_faults, store_faults=store_faults
    )
    return _adopt(smoke)


__all__ = [
    "DEMO_FAULT_INJECTED",
    "DEMO_OBSERVED",
    "FIXTURE_MAKE_DEMO_ENV",
    "FIXTURE_SCENARIO_RECORDER",
    "LABELS",
    "NOT_OBSERVED",
    "SCENARIO_EVIDENCE_SCHEMA",
    "SYNTHETIC",
    "EnvOptions",
    "FakeScenarioEnv",
    "ScenarioEnv",
    "ScenarioRecorder",
    "build_fake_scenario_env",
    "label_for",
]
