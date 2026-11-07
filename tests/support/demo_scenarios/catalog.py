"""The pinned S01-S20 scenario catalog of Phase 25 (plan 25-08).

TEST_ONLY and pure data: later scenario plans add only the files named here and never edit this
module or the harness. File names follow one rule:

* module `tests/support/demo_scenarios/s<NN>_<slug>.py` with `async def run(env, recorder) -> str`
* twin   `tests/test_demo_twin_s<NN>_<slug>.py`        (CI, fake composed process)
* demo   `tests/demo/test_demo_s<NN>_<slug>.py`        (owner-run, `-m demo`)

S20 is observation-only: it has no module, no twin and no demo test (owner probe records).
`leaves_state` marks a scenario that can leave the Demo account or the process state dirty (an
open position, a persisted DAILY_STOP, a foreign order): on failure its recorded step names
`scripts/demo_clear.py`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """One catalog entry; paths are repo-relative, None for the observation-only one."""

    id: str
    slug: str
    title: str
    roadmap_bullet: str
    plan: str
    requirements: tuple[str, ...]
    module: str | None
    twin_test: str | None
    demo_test: str | None
    observation_only: bool = False
    leaves_state: bool = False


def _scenario(
    number: int,
    slug: str,
    title: str,
    roadmap_bullet: str,
    plan: str,
    requirements: tuple[str, ...],
    *,
    leaves_state: bool = False,
) -> Scenario:
    stem = f"s{number:02d}_{slug}"
    return Scenario(
        id=f"S{number:02d}",
        slug=slug,
        title=title,
        roadmap_bullet=roadmap_bullet,
        plan=plan,
        requirements=requirements,
        module=f"tests/support/demo_scenarios/{stem}.py",
        twin_test=f"tests/test_demo_twin_{stem}.py",
        demo_test=f"tests/demo/test_demo_{stem}.py",
        leaves_state=leaves_state,
    )


SCENARIOS: tuple[Scenario, ...] = (
    _scenario(1, "happy", "Happy path", "happy path", "25-08", ("APRV-01", "EXEC-01", "OPS-02")),
    _scenario(2, "partial_fill", "Partial fill", "partial fill", "25-10", ("EXEC-01",)),
    _scenario(
        3,
        "crossed_stop",
        "Price crossed the stop before placement (-2021)",
        "price crossed SL before placement (-2021)",
        "25-11",
        ("EXEC-01",),
    ),
    _scenario(
        4,
        "stop_rejected",
        "Stop rejected after fill, reduce-only close",
        "SL rejected after fill -> reduce-only close",
        "25-11",
        ("EXEC-01", "OPS-01"),
    ),
    _scenario(
        5, "cancel_race", "Cancel racing a fill", "cancel racing a fill", "25-10", ("EXEC-01",)
    ),
    _scenario(
        6,
        "replay",
        "Duplicate or replayed APPROVE and CONFIRM",
        "duplicate/replayed APPROVE and CONFIRM callbacks",
        "25-10",
        ("EXEC-03", "APRV-02"),
    ),
    _scenario(
        7,
        "restart_cuts",
        "Restart mid-flow (three cuts)",
        "restart mid-flow (before entry ACK, between entry and SL, after fill)",
        "25-12",
        ("EXEC-01", "EXEC-03"),
    ),
    _scenario(
        8,
        "stream_loss",
        "WS disconnect and listenKey expiry",
        "WS disconnect and listenKey expiry",
        "25-13",
        ("EXEC-02", "OPS-01"),
    ),
    _scenario(9, "clock_skew", "Clock skew", "clock skew", "25-13", ("OPS-01",)),
    _scenario(
        10,
        "rate_limit",
        "Rate limit / 418 (injected only)",
        "rate limit / 418",
        "25-14",
        ("OPS-01",),
    ),
    _scenario(
        11,
        "db_outage",
        "DB outage during a risk-reducing action",
        "DB outage during a risk-reducing action",
        "25-14",
        ("OPS-01",),
    ),
    _scenario(
        12, "daily_stop", "DAILY_STOP", "DAILY_STOP", "25-15", ("OPS-01",), leaves_state=True
    ),
    _scenario(
        13,
        "margin_liquidation",
        "Liquidation-guard and available-margin rejections",
        "liquidation-guard and available-margin rejections",
        "25-15",
        ("OPS-01", "EXEC-01"),
    ),
    _scenario(
        14,
        "safe_mode",
        "SAFE_MODE entry and operator exit",
        "SAFE_MODE entry and operator exit",
        "25-15",
        ("OPS-01",),
    ),
    _scenario(
        15,
        "foreign_order",
        "Foreign order and doubled position",
        "foreign order and doubled position detected by reconcile",
        "25-16",
        ("EXEC-02", "OPS-01"),
        leaves_state=True,
    ),
    _scenario(
        16,
        "manual_close",
        "Manual close outside the system (G2-016)",
        "inherited G2-016: manual close outside the system",
        "25-16",
        ("EXEC-02", "OPS-01"),
        leaves_state=True,
    ),
    _scenario(
        17,
        "stale_feed",
        "Stale feed (G2-016)",
        "inherited G2-016: stale feed",
        "25-13",
        ("OPS-01",),
    ),
    _scenario(
        18,
        "unprotected",
        "Unprotected-position drill (G2-016)",
        "inherited G2-016: unprotected-position drill",
        "25-11",
        ("OPS-01",),
        leaves_state=True,
    ),
    _scenario(
        19,
        "rest_gate_cli",
        "REST gate operator commands (P20-DEMO)",
        "inherited P20-DEMO: rest_gate_cli status and clear",
        "25-14",
        ("OPS-01",),
    ),
    Scenario(
        id="S20",
        slug="observations",
        title="Observation-only items (D-07)",
        roadmap_bullet="D-07 observation-only items (owner probe records)",
        plan="25-06",
        requirements=("EXEC-01", "OPS-01"),
        module=None,
        twin_test=None,
        demo_test=None,
        observation_only=True,
    ),
)


def by_id(scenario_id: str) -> Scenario:
    """The catalog entry with this id; an unknown id raises KeyError (never a silent default)."""
    for scenario in SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(scenario_id)


__all__ = ["SCENARIOS", "Scenario", "by_id"]
