"""Rejected placements -1106, -4016, -4024: classification and what the table does not change.

Plan 18-26, owner decision of 2026-10-17 (decisions/18-DEC-TAXONOMY-CODES.md). A rejection by
one of these codes is REJECTED_DEFINITIVE on a placement and UNKNOWN_EXCHANGE_ERROR on every
other call kind. The taxonomy gives no placement a retry and never makes a rejected protective
order a protected one: the execution manager decides SAFE_MODE on ANY adapter exception of a
protective leg and does not read the taxonomy, and these tests assert that branch on the real
code path, not `safe_mode_eligible`.

The errors are SDK-shaped (`BadRequestError(error_message=..., status_code=<code>)`). The
Demo texts below are the ones recorded in evidence/18-probe-check.txt (2026-10-16); the page
texts are those of evidence/18-error-code-page-reread-20261017.txt. Synthetic, not live.
"""

from __future__ import annotations

import asyncio
import json
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

from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.test_binance_usdm_signed_calls import (
    RecordingHook,
    _adapter,
    _place_entry,
    _protective,
)
from tests.test_binance_usdm_signed_calls import _run as _run_coro
from tests.test_execution_attach import FakeExecutionAdapter as AttachAdapter
from tests.test_execution_attach import _attach, _load_expected
from tests.test_execution_attach import _RecordingSafeModeController as AttachSafeMode
from tests.test_execution_manager import (
    FakeExecutionAdapter,
    FakeJournal,
    RecordingSafeModeController,
    _load_input,
    _probe,
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
# Tracer: -1106 on the protective stop still ends in ENTRY_WITHOUT_PROTECTIVE.
# --------------------------------------------------------------------------- #


class _ProtectiveRaises(FakeExecutionAdapter):
    """A fake adapter whose protective placement raises the given SDK-shaped error."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def place_algo_protective(self, **kwargs: Any) -> Any:
        await super().place_algo_protective(**kwargs)
        raise self.error


class _NoOpTruth:
    async def snapshot_open_normal_orders(self, *, symbol: Any = None) -> list[Any]:
        return []

    async def snapshot_open_algo_orders(self, *, symbol: Any = None) -> list[Any]:
        return []

    async def snapshot_positions(self, *, symbol: Any = None) -> list[Any]:
        return []


@pytest.mark.parametrize("controller_kind", ["recording_double", "real_controller"])
async def test_tracer_1106_on_the_protective_stop_is_entry_without_protective(
    controller_kind: str,
) -> None:
    """The SAFE_MODE decision belongs to the manager (any adapter exception of a protective
    leg is an unconfirmed leg), not to `safe_mode_eligible`, which is False for -1106."""
    from src.reconcile.safe_mode import SafeModeController

    recording = RecordingSafeModeController()
    real = SafeModeController(adapter=_NoOpTruth(), journal=FakeJournal())
    controller: Any = recording if controller_kind == "recording_double" else real
    adapter = _ProtectiveRaises(_sdk_error(-1106, DEMO_1106))
    journal = FakeJournal()
    store = InMemoryExecutionIntentStore()

    outcome = await _run_plan(
        adapter, safe_mode_controller=controller, journal=journal, intent_store=store
    )

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    if controller_kind == "recording_double":
        assert recording.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    else:
        assert real.in_safe_mode is True
        follow_up = FakeExecutionAdapter()
        blocked = await _run_plan(follow_up, safe_mode_controller=real)
        assert (blocked.is_no_trade, blocked.reason_code) == (True, "RECONCILIATION_REQUIRED")
        assert follow_up.calls == []
    methods = [call["method"] for call in adapter.calls]
    protective = [call for call in adapter.calls if call["method"] == "place_algo_protective"]
    assert len(protective) == 1
    assert protective[0]["kwargs"]["close_position"] is True  # the stop; no take profit exists
    assert methods[-1] == "cancel_normal_order"
    assert adapter.calls[-1]["kwargs"]["orig_client_order_id"] == derive_client_order_id(
        plan_hash=_load_input()["plan_hash"], role="ENTRY"
    )
    assert [json_phase(event) for event in journal.events] == ["pre_cancel", "post_cancel"]
    case_input = _load_input()
    stop_loss = store.get_intent(approval_id=case_input["approval_id"], role="STOP_LOSS")
    assert stop_loss is not None
    assert stop_loss.intent_status == ExecutionIntentStatus.UNKNOWN
    assert stop_loss.intent_status != ExecutionIntentStatus.ACKED
    entry = store.get_entry(approval_id=case_input["approval_id"])
    assert entry is not None and entry.outcome is not None
    assert entry.outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE"


def json_phase(event: Any) -> str:
    return str(json.loads(event.payload_json)["phase"])


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
async def test_safe_mode_eligible_is_false_but_the_manager_branch_still_fires(
    code: int, text: str
) -> None:
    """The taxonomy says False for the PLACEMENT category of each code; the manager still
    enters SAFE_MODE because it treats any adapter exception of the stop as unconfirmed."""
    facts = error_facts_from_exception(_sdk_error(code, text))
    assert safe_mode_eligible(classify(facts, _K.PLACEMENT)) is False
    adapter = _ProtectiveRaises(_sdk_error(code, text))
    safe_mode = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]
    assert [call["method"] for call in adapter.calls].count("place_algo_protective") == 1
    assert [call["method"] for call in adapter.calls][-1] == "cancel_normal_order"


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
def test_rejected_stop_loss_in_attach_is_entry_without_protective(code: int, text: str) -> None:
    expected = _load_expected()

    class _StopRejected(AttachAdapter):
        async def place_algo_protective(self, **kwargs: Any) -> Any:
            await super().place_algo_protective(**kwargs)
            raise _sdk_error(code, text)

    adapter = _StopRejected()
    safe_mode = AttachSafeMode()

    outcome = _attach(adapter, safe_mode)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert outcome.placed_legs == ()
    assert outcome.failure_detail == "STOP_LOSS: BadRequestError"  # never the message text
    assert [c["kwargs"]["client_algo_id"] for c in adapter.calls] == [expected["sl_algo_client_id"]]
    assert safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]


def test_rejected_take_profit_in_attach_is_entry_without_protective() -> None:
    expected = _load_expected()

    class _Tp1Rejected(AttachAdapter):
        async def place_algo_protective(self, **kwargs: Any) -> Any:
            if kwargs.get("client_algo_id") == expected["tp1_algo_client_id"]:
                await super().place_algo_protective(**kwargs)
                raise _sdk_error(-4016, DEMO_4016)
            return await super().place_algo_protective(**kwargs)

    adapter = _Tp1Rejected()
    safe_mode = AttachSafeMode()

    outcome = _attach(adapter, safe_mode)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "ENTRY_WITHOUT_PROTECTIVE")
    assert outcome.placed_legs == ("STOP_LOSS",)
    assert outcome.failure_detail == "TAKE_PROFIT_1: BadRequestError"
    placed_ids = [c["kwargs"]["client_algo_id"] for c in adapter.calls]
    assert placed_ids == [expected["sl_algo_client_id"], expected["tp1_algo_client_id"]]
    assert expected["tp2_algo_client_id"] not in placed_ids
    assert safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"]


@pytest.mark.parametrize(("code", "text"), OWNER_CASES[1:], ids=OWNER_IDS[1:])
async def test_entry_rejection_sequence_is_unchanged_by_the_table(code: int, text: str) -> None:
    """Characterization, written and run green BEFORE the -4016 and -4024 rows were added.

    The manager does not consult the taxonomy, so a rejected ENTRY follows its own bounded
    query-first sequence: the same prices are sent once more after a probe that finds the
    order absent, and the table adds no call (no mark price, filter or snapshot refresh, no
    new method). Refreshing them is the consumer's job (open items (a) and (c) of
    decisions/18-DEC-TAXONOMY-CODES.md).
    """
    adapter = FakeExecutionAdapter()
    adapter.entry_exceptions.extend([_sdk_error(code, text), _sdk_error(code, text)])
    adapter.query_responses.extend([_probe(found=False), _probe(found=False)])
    safe_mode = RecordingSafeModeController()

    outcome = await _run_plan(adapter, safe_mode_controller=safe_mode)

    assert (outcome.is_no_trade, outcome.reason_code) == (True, "EXCHANGE_CONSTRAINT")
    methods = [call["method"] for call in adapter.calls]
    assert methods == [
        "get_position_mode",
        "place_entry",
        "query_order_by_client",
        "place_entry",
        "query_order_by_client",
    ]
    assert "place_algo_protective" not in methods
    entries = [call["kwargs"] for call in adapter.calls if call["method"] == "place_entry"]
    assert len(entries) == 2
    assert entries[0] == entries[1]
    assert safe_mode.entered_reasons == []
