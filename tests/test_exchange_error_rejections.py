"""Rejected placements -1106, -4016, -4024: classification and what the table does not change.

Plan 18-26, owner decision of 2026-10-17 (decisions/18-DEC-TAXONOMY-CODES.md). A rejection by
one of these codes is REJECTED_DEFINITIVE on a placement and UNKNOWN_EXCHANGE_ERROR on every
other call kind. The taxonomy gives no placement a retry and never makes a rejected protective
order a protected one: the protection coordinator (plans 19-11 and 19-14, driven after a fill;
plan 19-15 moved the stop out of the manager) reads the taxonomy for the stop and goes
CLOSE_REQUIRED on a definitive rejection, and these tests assert that branch on the real code
path, not `safe_mode_eligible`.

The errors are SDK-shaped (`BadRequestError(error_message=..., status_code=<code>)`). The
Demo texts below are the ones recorded in evidence/18-probe-check.txt (2026-10-16); the page
texts are those of evidence/18-error-code-page-reread-20261017.txt. Synthetic, not live.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from src.adapters.binance_errors import error_facts_from_exception
from src.domain.enums import ExecutionIntentStatus
from src.domain.exchange_errors import (
    CallKind,
    ErrorFacts,
    ExchangeErrorCategory,
    HttpClass,
    classify,
    retry_eligible,
    safe_mode_eligible,
)
from src.execution.order_ids import derive_client_order_id
from src.execution.protection import ProtectionState

from tests.support.protection_doubles import TEST_ONLY_PLAN_HASH, ProtectionRig, make_rig
from tests.test_binance_usdm_signed_calls import (
    RecordingHook,
    _adapter,
    _place_entry,
    _protective,
)
from tests.test_binance_usdm_signed_calls import _run as _run_coro
from tests.test_execution_attach import STOP_ID, TP1_ID, TP2_ID, protected_rig, run_attach
from tests.test_execution_manager import (
    PRE_PLACEMENT_READS,
    FakeExecutionAdapter,
    RecordingSafeModeController,
    _run_plan,
)

_C = ExchangeErrorCategory
_K = CallKind

DEMO_1106 = "Parameter 'reduceonly' sent when not required."
PAGE_1106 = "A parameter was sent when not required."
# The Demo wording of -4016 (evidence/18-probe-check.txt) and the page wording of -4024
# (evidence/18-error-code-page-reread-20261017.txt; -4024 was not observed on the Demo).
DEMO_4016 = "Limit price can't be higher than 86305.10."
PAGE_4016 = "Price is higher than mark price multiplier cap."
PAGE_4024 = "Price is lower than mark price multiplier floor."

OWNER_CASES: list[tuple[int, str]] = [(-1106, DEMO_1106), (-4016, DEMO_4016), (-4024, PAGE_4024)]
OWNER_IDS = [f"code{code}" for code, _ in OWNER_CASES]


def _sdk_error(code: int, text: str) -> BadRequestError:
    return BadRequestError(error_message=text, status_code=code)


# --------------------------------------------------------------------------- #
# Tracer: -1106 from the SDK error to the table.
# --------------------------------------------------------------------------- #


def test_tracer_1106_classifies_rejected_definitive_on_placement_only() -> None:
    facts = error_facts_from_exception(_sdk_error(-1106, DEMO_1106))
    assert facts == ErrorFacts(HttpClass.BAD_REQUEST, -1106, None)
    assert classify(facts, _K.PLACEMENT) is _C.REJECTED_DEFINITIVE
    for kind in (_K.QUERY, _K.CANCEL, _K.LISTEN_KEY, _K.TIME):
        assert classify(facts, kind) is _C.UNKNOWN_EXCHANGE_ERROR, kind
    # The message text is never read: the page wording and an empty text classify the same.
    for text in (PAGE_1106, "", "something else entirely"):
        same = error_facts_from_exception(_sdk_error(-1106, text))
        assert same == facts
        for kind in CallKind:
            assert classify(same, kind) is classify(facts, kind)
    for kind in CallKind:
        category = classify(facts, kind)
        assert retry_eligible(category, kind) is False, kind
        # The code alone does not prove a wrong position mode (owner point 1).
        assert category is not _C.POSITION_MODE, kind
    assert safe_mode_eligible(classify(facts, _K.PLACEMENT)) is False


# --------------------------------------------------------------------------- #
# Tracer: -1106 on the protective stop AFTER A FILL goes CLOSE_REQUIRED (plan 19-15, D-10).
# --------------------------------------------------------------------------- #


async def _stop_rejected_after_a_fill(code: int, text: str) -> ProtectionRig:
    rig = await make_rig(real_closer=True)
    rig.fake.reject_next_algo(code, text)
    rig.coordinator.fill_sink(rig.stream_fill(Decimal("0.004")))
    await rig.coordinator.step()
    return rig


def _assert_close_required_after_a_rejected_stop(rig: ProtectionRig) -> None:
    """B5 semantics: the stop is REJECTED (never ACKED), never resent, the plan is CLOSE_REQUIRED
    and the exposure is closed by exactly one reduce-only MARKET order."""
    stop_row = rig.stop_row()
    assert stop_row is not None
    assert stop_row.intent_status == ExecutionIntentStatus.REJECTED
    assert stop_row.intent_status != ExecutionIntentStatus.ACKED
    protection = rig.coordinator.protection_of(TEST_ONLY_PLAN_HASH)
    assert protection is not None
    assert protection.state is ProtectionState.CLOSE_REQUIRED
    assert rig.coordinator.blocks_new_entries() is True
    assert rig.safe_mode.entered_reasons == ["CLOSE_REQUIRED"]
    assert [(a.event, a.reason) for a in rig.alerts.alerts] == [
        ("CLOSE_REQUIRED", "B5_STOP_REJECTED"),
        ("PROTECTIVE_REJECTED", "B5_STOP_REJECTED"),
    ]
    assert len(rig.fake.calls_to("place_algo_protective")) == 1  # never resent
    assert len(rig.fake.calls_to("place_market_close")) == 1


async def test_tracer_1106_on_the_protective_stop_after_a_fill_goes_close_required() -> None:
    """The decision belongs to the coordinator: the taxonomy says REJECTED_DEFINITIVE on a
    placement, so the stop is not resent and the position is closed. `safe_mode_eligible` stays
    False for -1106 (SAFE_MODE comes from CLOSE_REQUIRED, not from the taxonomy flag)."""
    rig = await _stop_rejected_after_a_fill(-1106, DEMO_1106)
    _assert_close_required_after_a_rejected_stop(rig)
    # The entry cancel went out through the deterministic entry id.
    cancels = rig.fake.calls_to("cancel_normal_order")
    assert cancels
    assert cancels[0]["kwargs"]["orig_client_order_id"] == derive_client_order_id(
        plan_hash=TEST_ONLY_PLAN_HASH, role="ENTRY"
    )


# --------------------------------------------------------------------------- #
# Expansion: -1106, -4016 and -4024 (plan 18-26 Task 2).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
@pytest.mark.parametrize("http_class", [HttpClass.BAD_REQUEST, HttpClass.NOT_FOUND])
def test_each_owner_code_classifies_rejected_definitive_on_placement_only(
    code: int, text: str, http_class: HttpClass
) -> None:
    facts = ErrorFacts(http_class, code, None)
    assert classify(facts, _K.PLACEMENT) is _C.REJECTED_DEFINITIVE
    for kind in (_K.QUERY, _K.CANCEL, _K.LISTEN_KEY, _K.TIME):
        assert classify(facts, kind) is _C.UNKNOWN_EXCHANGE_ERROR, kind
    # The SDK-shaped error carries the same facts whatever the message text says.
    plain = ErrorFacts(HttpClass.BAD_REQUEST, code, None)
    for message in (text, PAGE_1106, PAGE_4016, PAGE_4024, DEMO_4016, ""):
        from_sdk = error_facts_from_exception(_sdk_error(code, message))
        assert from_sdk == plain
        for kind in CallKind:
            assert classify(from_sdk, kind) is classify(plain, kind)
    for kind in CallKind:
        assert classify(facts, kind) is not _C.POSITION_MODE


@pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
def test_no_owner_code_is_retry_eligible_for_any_call_kind(code: int, text: str) -> None:
    facts = error_facts_from_exception(_sdk_error(code, text))
    for kind in CallKind:
        assert retry_eligible(classify(facts, kind), kind) is False, kind
    assert retry_eligible(_C.REJECTED_DEFINITIVE, _K.PLACEMENT) is False


@pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
async def test_safe_mode_eligible_is_false_but_the_coordinator_branch_still_fires(
    code: int, text: str
) -> None:
    """The taxonomy says False for the PLACEMENT category of each code; the coordinator still
    enters SAFE_MODE (CLOSE_REQUIRED) because a definitively rejected stop leaves a fill
    without protection, and it closes the position instead of resending the stop."""
    facts = error_facts_from_exception(_sdk_error(code, text))
    assert safe_mode_eligible(classify(facts, _K.PLACEMENT)) is False

    rig = await _stop_rejected_after_a_fill(code, text)

    _assert_close_required_after_a_rejected_stop(rig)


@pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
@pytest.mark.parametrize(
    ("method", "sdk_name"),
    [("place_entry", "new_order"), ("place_algo_protective", "new_algo_order")],
)
def test_adapter_makes_one_sdk_call_per_placement_and_reraises_unchanged(
    code: int, text: str, method: str, sdk_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("a real asyncio.sleep was called")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)
    hook = RecordingHook()
    adapter, rest, sleep, gate = _adapter(on_clock_skew=hook)
    assert gate is not None
    error = _sdk_error(code, text)
    # A second scripted error would be consumed only by a retry.
    rest.fail(sdk_name, error, _sdk_error(code, text))
    call = _place_entry if method == "place_entry" else _protective

    with pytest.raises(BadRequestError) as info:
        _run_coro(call(adapter))

    assert info.value is error
    assert rest.calls[sdk_name] == 1
    assert rest.total() == 1
    assert sleep.waits == []
    assert gate.restriction() is None
    assert hook.calls == 0


@pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
async def test_rejected_take_profit_in_attach_is_entry_without_protective_and_keeps_the_stop(
    code: int, text: str
) -> None:
    """Plan 19-16 (D-17): attach never places a stop, so the owner codes reach it on a take-profit
    leg. A definitively rejected TP1 holds ENTRY_WITHOUT_PROTECTIVE with SAFE_MODE, names the
    exception TYPE only (never the message text), leaves TP2 unsent and the confirmed stop in
    place, and closes the TP1 intent as REJECTED (it replaces the plan 18-26 stop test)."""
    rig = await protected_rig()
    rig.fake.reject_next_algo(code, text)

    outcome = await run_attach(rig)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert outcome.failure_detail == "TAKE_PROFIT_1: BadRequestError"  # never the message text
    assert [c["kwargs"]["client_algo_id"] for c in rig.fake.calls_to("place_algo_protective")] == [
        TP1_ID
    ]
    assert rig.safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    assert STOP_ID in rig.fake.open_algos
    tp1_row = rig.inner_store.get_intent(approval_id=rig.entry.approval_id, role="TAKE_PROFIT_1")
    assert tp1_row.intent_status is ExecutionIntentStatus.REJECTED


async def test_rejected_second_take_profit_in_attach_keeps_tp1_and_the_stop() -> None:
    rig = await protected_rig()
    original = rig.fake.place_algo_protective

    async def reject_tp2(**kwargs: Any) -> Any:
        if kwargs["client_algo_id"] == TP2_ID:
            rig.fake.reject_next_algo(-4016, DEMO_4016)
        return await original(**kwargs)

    rig.fake.place_algo_protective = reject_tp2  # type: ignore[method-assign]

    outcome = await run_attach(rig)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert outcome.placed_legs == ("STOP_LOSS", "TAKE_PROFIT_1")
    assert outcome.failure_detail == "TAKE_PROFIT_2: BadRequestError"
    assert {STOP_ID, TP1_ID} <= set(rig.fake.open_algos)
    assert rig.safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]


@pytest.mark.parametrize(("code", "text"), OWNER_CASES, ids=OWNER_IDS)
async def test_entry_rejection_by_an_owner_code_is_definitive_and_not_retried(
    code: int, text: str
) -> None:
    """Plan 19-15 (D-21): the manager now reads the taxonomy on the entry path. A placement
    rejected by -1106, -4016 or -4024 is REJECTED_DEFINITIVE, so there is no probe and no second
    send of the same prices (it replaces the plan 18-26 characterization, which pinned the old
    probe-then-resend sequence). Refreshing the mark price and the filters after -4016 or
    -4024 stays the consumer's job (open items (a) and (c) of
    decisions/18-DEC-TAXONOMY-CODES.md)."""
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.append(_sdk_error(code, text))
    safe_mode = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "EXCHANGE_CONSTRAINT")
    methods = [call["method"] for call in adapter.calls]
    assert methods == [*PRE_PLACEMENT_READS, "get_position_mode", "place_entry"]
    assert safe_mode.entered_reasons == []
