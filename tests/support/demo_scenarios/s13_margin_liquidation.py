"""S13 margin and liquidation guards (plan 25-15; OPS-01, EXEC-01, D-05, gate 5f2).

TEST_ONLY. Gate 5f2 of the placement path (`MarginGuard`) refuses before anything is sent: an
available balance below the margin the plan needs, and a liquidation price that is not beyond the
stop by the owner's buffer. The Demo account cannot be put in either state on demand, so the two
readings are injected at the adapter edge (`FaultEdge.override`, DEMO_FAULT_INJECTED) and the
guards' reactions are the real process's. The exchange-side -2019 stays with the owner probe case
`insufficient_margin_order` (Demo-observed 2026-10-24).

Both injected values are computed from what the process built and loaded, never typed in:

* margin: the plan's quantity and zone-mid entry price over the target leverage give the initial
  margin the plan needs; the injected `available_balance` (the account figure and the USDT asset row
  together, so the guard's own cross-check of the two holds) is half of it. The real snapshot is
  read through the edge's inner adapter and only those two fields are replaced.
* liquidation: the maintenance ratio `m` of a one-bracket table is solved from the closed form of
  `src/risk/liquidation.py` so that the liquidation price sits half way between the entry and the
  stop (LONG `LP = EP (1 - w) / (1 - m)`, SHORT `LP = EP (1 + w) / (1 + m)`, `w = 1 / L`, `cum`
  zero); the floor, the cap and the initial leverage come from the account's real bracket table.

Order: margin refusal, a normal placement (the overrides cleared), then the liquidation refusal. The
process keeps a bracket reading for `margin.max_bracket_age_ms`, so the bad-bracket case runs last
and waits that bound once, so that its CONFIRM reads the table again and sees the override; running
it earlier would make the next request see a bad table for a minute.

Each refusal asserts the plain reason code, that no `place_entry` and no symbol-configuration POST
(`change_margin_type`, `change_initial_leverage`) reached the edge, and that the approval stays
unconsumed (it is expired by the scenario). The normal request is placed, acknowledged and cancelled
by its client id; `account_clean` ends the run.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

from scripts import demo_rehearsal as dr
from src.adapters.binance_usdm import LeverageBracketRow, SymbolLeverageBrackets
from src.execution.symbol_config_guard import TARGET_LEVERAGE
from src.live.wiring import QUOTE_ASSET

from tests.support.demo_scenarios.harness import (
    ScenarioRecorder,
    account_clean,
    ensure_clean_start,
)
from tests.support.demo_scenarios.s04_stop_rejected import record_injection_step, record_step
from tests.support.demo_scenarios.s06_replay import (
    cancel_resting_entry,
    place_approved_entry,
    place_entry_calls,
    shutdown,
    start_evidence,
)
from tests.support.demo_scenarios.s08_stream_loss import (
    card_and_approve,
    expire_plan,
    placement_decision,
    ticks,
)

SCENARIO_FAR = "far"
ACCOUNT_METHOD = "account_information_snapshot"
BRACKETS_METHOD = "leverage_brackets_snapshot"
CONFIG_POST_METHODS = ("change_margin_type", "change_initial_leverage")
MARGIN_REASON = "INSUFFICIENT_MARGIN"
LIQUIDATION_REASON = "LIQUIDATION_TOO_CLOSE"
_TWO = Decimal(2)
_RATIO_PLACES = Decimal("0.00000001")

STEP_MARGIN_INJECT = "inject_low_available_balance"
STEP_MARGIN_REFUSED = "margin_guard_refuses_before_placement"
STEP_ENTRY_PLACED = "entry_placed_with_the_overrides_cleared"
STEP_LIQUIDATION_INJECT = "inject_narrow_liquidation_distance"
STEP_LIQUIDATION_REFUSED = "liquidation_guard_refuses_before_placement"


def record_inject(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """An injected reading: DEMO_FAULT_INJECTED on Demo, never DEMO_OBSERVED."""
    record_injection_step(env, recorder, detail, name=name)


def record_reaction(env: Any, recorder: ScenarioRecorder, name: str, detail: str) -> None:
    """A reaction of the real process: the env label."""
    record_step(env, recorder, name, detail)


# ---- values derived from the plan -------------------------------------------------------------- #


async def plan_values(env: Any, request: Any) -> dict[str, Any]:
    """The built plan's quantity, zone-mid entry, stop and side, and the target leverage."""
    plan = await dr._smoke_read(
        env, env.wiring.stores.entities.get_trade_plan, request.trade_plan_id
    )
    if plan is None:
        raise dr.SmokeHalt("plan_unreadable")
    entry = (plan.entry_min_price + plan.entry_max_price) / _TWO
    stop = plan.stop_loss_price
    return {
        "side": "LONG" if stop < entry else "SHORT",
        "quantity": plan.quantity_after_rounding,
        "entry_price": entry,
        "stop_price": stop,
        "leverage": TARGET_LEVERAGE,
    }


def needed_initial_margin(values: dict[str, Any]) -> Decimal:
    """Initial margin of the plan: quantity times the zone-mid price over the target leverage."""
    return (
        Decimal(values["quantity"]) * Decimal(values["entry_price"]) / Decimal(values["leverage"])
    )


def liquidation_target(values: dict[str, Any]) -> Decimal:
    """A liquidation price half way between the entry and the stop (inside the stop)."""
    return (Decimal(values["entry_price"]) + Decimal(values["stop_price"])) / _TWO


def inside_the_stop_ratio(values: dict[str, Any]) -> Decimal:
    """The maintenance ratio `m` (cum zero) that puts the liquidation price at the target."""
    entry = Decimal(values["entry_price"])
    wallet_share = Decimal(1) / Decimal(values["leverage"])
    target = liquidation_target(values)
    if values["side"] == "LONG":
        ratio = Decimal(1) - entry * (Decimal(1) - wallet_share) / target
    else:
        ratio = entry * (Decimal(1) + wallet_share) / target - Decimal(1)
    return ratio.quantize(_RATIO_PLACES)


# ---- the overrides ----------------------------------------------------------------------------- #


def _low_available(env: Any, available: Decimal) -> Any:
    """The account read with only the free-margin figures replaced (account level and USDT row)."""

    async def read(**kwargs: Any) -> Any:
        real = await env.faults.inner.account_information_snapshot(**kwargs)
        assets = tuple(
            dataclasses.replace(row, available_balance=available)
            if row.asset == QUOTE_ASSET
            else row
            for row in real.assets
        )
        return dataclasses.replace(real, available_balance=available, assets=assets)

    return read


def _narrow_brackets(env: Any, ratio: Decimal) -> Any:
    """A one-bracket table with the derived ratio; floor, cap and leverage are the real ones."""

    async def read(**kwargs: Any) -> Any:
        real = await env.faults.inner.leverage_brackets_snapshot(**kwargs)
        row = LeverageBracketRow(
            bracket=1,
            initial_leverage=max(item.initial_leverage for item in real.brackets),
            notional_floor=Decimal(0),
            notional_cap=real.brackets[-1].notional_cap,
            maint_margin_ratio=ratio,
            cum=Decimal(0),
        )
        return SymbolLeverageBrackets(
            symbol=real.symbol, notional_coef=real.notional_coef, brackets=(row,)
        )

    return read


def _injected_reads(env: Any, method: str) -> int:
    return len([c for c in env.faults.calls_to(method) if c["injected"] is True])


def _config_posts(env: Any) -> int:
    return sum(len(env.faults.calls_to(method)) for method in CONFIG_POST_METHODS)


# ---- the scenario ------------------------------------------------------------------------------ #


async def run(env: Any, recorder: ScenarioRecorder) -> str:
    """Run S13 on `env`; returns the outcome. A failed step raises `dr.SmokeHalt`."""
    recorder.default_label = env.label
    await ensure_clean_start(env, recorder)
    try:
        return await _sequence(env, recorder)
    finally:
        env.faults.clear(ACCOUNT_METHOD)
        env.faults.clear(BRACKETS_METHOD)
        await shutdown(env)


async def _sequence(env: Any, recorder: ScenarioRecorder) -> str:
    start_evidence(env, recorder)
    await dr._bring_up(env, recorder, "start")
    facts: dict[str, Any] = recorder.details.setdefault("margin_liquidation", {})

    await _margin_refusal(env, recorder, facts)
    await _normal_request(env, recorder, facts)
    await _liquidation_refusal(env, recorder, facts)
    if not await account_clean(env, recorder):
        raise dr.SmokeHalt("account_clean")
    recorder.outcome = dr.OUTCOME_COMPLETE
    return dr.OUTCOME_COMPLETE


async def _confirm_and_read(
    env: Any, recorder: ScenarioRecorder, request: Any, step: str
) -> list[dict[str, Any]]:
    await env.owner.act("confirm", short_id=request.short_id, note="")

    async def decided() -> bool:
        return bool(await placement_decision(env, request))

    if not await dr._wait_until(env, decided):
        raise dr._smoke_fail(env, recorder, step, "the CONFIRM left no journaled decision")
    decisions: list[dict[str, Any]] = await placement_decision(env, request)
    return decisions


def _plan_facts(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "side": values["side"],
        "quantity": str(values["quantity"]),
        "entry_price": str(values["entry_price"]),
        "stop_price": str(values["stop_price"]),
        "leverage": values["leverage"],
    }


async def _refusal_facts(
    env: Any,
    recorder: ScenarioRecorder,
    step: str,
    expected: str,
    request: Any,
    sent_before: int,
    posts_before: int,
) -> dict[str, Any]:
    decisions = await _confirm_and_read(env, recorder, request, step)
    facts = {
        "reason": decisions[-1]["reason"] if decisions else None,
        "decisions": decisions,
        "place_entry_calls_before": sent_before,
        "place_entry_calls_after": place_entry_calls(env),
        "config_posts": _config_posts(env) - posts_before,
    }
    if (
        not decisions
        or not all(d["refused"] for d in decisions)
        or facts["reason"] != expected
        or facts["place_entry_calls_after"] != sent_before
        or facts["config_posts"] != 0
    ):
        raise dr._smoke_fail(
            env,
            recorder,
            step,
            f"decisions {decisions}, place_entry {facts['place_entry_calls_after']} (was "
            f"{sent_before}), configuration POSTs {facts['config_posts']}; expected a refusal "
            f"{expected} with nothing sent",
        )
    return facts


async def _margin_refusal(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    request = await card_and_approve(env, recorder)
    values = await plan_values(env, request)
    facts["plan"] = _plan_facts(values)
    needed = needed_initial_margin(values)
    available = needed / _TWO
    sent_before, posts_before = place_entry_calls(env), _config_posts(env)
    env.faults.override(ACCOUNT_METHOD, _low_available(env, available), times=None)
    record_inject(
        env,
        recorder,
        STEP_MARGIN_INJECT,
        f"account_information_snapshot returns an available balance of {available} (account and "
        f"{QUOTE_ASSET} row) against an initial margin of {needed} at {values['leverage']}x",
    )
    refusal = await _refusal_facts(
        env, recorder, STEP_MARGIN_REFUSED, MARGIN_REASON, request, sent_before, posts_before
    )
    refusal.update(
        {
            "needed_initial_margin": str(needed),
            "available_injected": str(available),
            "injected_reads": _injected_reads(env, ACCOUNT_METHOD),
        }
    )
    facts["margin"] = refusal
    env.faults.clear(ACCOUNT_METHOD)
    if refusal["injected_reads"] < 1:
        raise dr._smoke_fail(
            env, recorder, STEP_MARGIN_REFUSED, "no account read reached the injected override"
        )
    record_reaction(
        env,
        recorder,
        STEP_MARGIN_REFUSED,
        f"the margin guard refused the CONFIRM ({MARGIN_REASON}) before any entry or "
        "configuration POST was sent",
    )
    await expire_plan(env, request)
    await ticks(env, 3)  # the reservation of the expired plan is released


async def _normal_request(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    sent_before = place_entry_calls(env)
    request = await place_approved_entry(env, recorder, SCENARIO_FAR)
    facts["normal"] = {"placed": True, "place_entry_calls": place_entry_calls(env) - sent_before}
    record_reaction(
        env,
        recorder,
        STEP_ENTRY_PLACED,
        "with the overrides cleared the request was placed once and acknowledged",
    )
    await cancel_resting_entry(env, recorder, request)


async def _liquidation_refusal(env: Any, recorder: ScenarioRecorder, facts: dict[str, Any]) -> None:
    age_ms = env.assembly.config.limits.margin_max_bracket_age_ms
    await env.pause(-(-int(age_ms) // 1000) + 1)  # the cached bracket reading has expired
    request = await card_and_approve(env, recorder)
    values = await plan_values(env, request)
    ratio = inside_the_stop_ratio(values)
    target = liquidation_target(values)
    if not Decimal(0) < ratio < Decimal(1):
        raise dr._smoke_fail(
            env,
            recorder,
            STEP_LIQUIDATION_INJECT,
            f"the derived maintenance ratio {ratio} is not a usable bracket value",
        )
    sent_before, posts_before = place_entry_calls(env), _config_posts(env)
    env.faults.override(BRACKETS_METHOD, _narrow_brackets(env, ratio), times=None)
    record_inject(
        env,
        recorder,
        STEP_LIQUIDATION_INJECT,
        f"leverage_brackets_snapshot returns one bracket with a maintenance ratio of {ratio}: a "
        f"{values['side']} entering at {values['entry_price']} with the stop at "
        f"{values['stop_price']} then liquidates near {target}, inside the stop",
    )
    refusal = await _refusal_facts(
        env,
        recorder,
        STEP_LIQUIDATION_REFUSED,
        LIQUIDATION_REASON,
        request,
        sent_before,
        posts_before,
    )
    refusal.update(
        {
            "maint_margin_ratio_injected": str(ratio),
            "liquidation_price_target": str(target),
            "injected_reads": _injected_reads(env, BRACKETS_METHOD),
        }
    )
    facts["liquidation"] = refusal
    env.faults.clear(BRACKETS_METHOD)
    if refusal["injected_reads"] < 1:
        raise dr._smoke_fail(
            env, recorder, STEP_LIQUIDATION_REFUSED, "no bracket read reached the override"
        )
    record_reaction(
        env,
        recorder,
        STEP_LIQUIDATION_REFUSED,
        f"the liquidation guard refused the CONFIRM ({LIQUIDATION_REASON}) before any entry or "
        "configuration POST was sent",
    )
    await expire_plan(env, request)
